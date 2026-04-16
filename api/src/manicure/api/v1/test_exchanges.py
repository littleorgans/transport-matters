"""Tests for the exchanges API endpoints."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from manicure import config
from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from manicure.main import create_app
from manicure.storage import init_storage, reset_storage
from manicure.storage.base import ExchangeArtifacts, IndexEntry, PipelineStats, ReqStats

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _setup_storage(tmp_path: Path) -> Generator[None]:
    """Initialise storage with a temp dir before each test."""
    reset_storage()
    init_storage(root=tmp_path)
    yield
    reset_storage()


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Generator[None]:
    config.get_settings.cache_clear()
    yield
    config.get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_counting_state() -> Generator[None]:
    """Reset process-wide counter and auth cache between tests.

    The lazy pipeline_tokens endpoint reads from these; leaving state
    between tests would make one case leak into the next.
    """
    from manicure import counting
    from manicure.api.v1 import exchanges

    counting.set_counter(None)
    counting.set_recent_auth(None)
    exchanges._compute_locks.clear()
    yield
    counting.set_counter(None)
    counting.set_recent_auth(None)
    exchanges._compute_locks.clear()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _make_index_entry(
    entry_id: str = "ex-001", *, run_id: str | None = None
) -> IndexEntry:
    return IndexEntry(
        id=entry_id,
        run_id=run_id,
        ts=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        provider="anthropic",
        model="anthropic/claude-sonnet-4-20250514",
        path="exchanges/20250601T120000-ex-001/",
        req=ReqStats(
            system_parts=0,
            system_chars=0,
            tools_count=0,
            tools_chars=0,
            messages_count=1,
            messages_chars=2,
            total_chars=2,
        ),
    )


def _make_ir() -> InternalRequest:
    return InternalRequest(
        model="anthropic/claude-sonnet-4-20250514",
        provider="anthropic",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hi")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


class TestListExchanges:
    async def test_list_empty(self, client: AsyncClient) -> None:
        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_after_write_for_current_run(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from manicure.storage import get_storage

        monkeypatch.setenv("MANICURE_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        entry = _make_index_entry(run_id="run-current")
        await storage.append_index(entry)

        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "ex-001"

    async def test_list_hides_other_runs_by_default(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from manicure.storage import get_storage

        monkeypatch.setenv("MANICURE_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        await storage.append_index(_make_index_entry("ex-old", run_id="run-old"))
        await storage.append_index(_make_index_entry("ex-new", run_id="run-current"))

        response = await client.get("/api/exchanges")
        assert response.status_code == 200
        data = response.json()
        assert [row["id"] for row in data] == ["ex-new"]

    async def test_list_include_history_returns_all_runs(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from manicure.storage import get_storage

        monkeypatch.setenv("MANICURE_RUN_ID", "run-current")
        config.get_settings.cache_clear()
        storage = await get_storage()
        await storage.append_index(_make_index_entry("ex-old", run_id="run-old"))
        await storage.append_index(_make_index_entry("ex-new", run_id="run-current"))

        response = await client.get("/api/exchanges?include_history=true")
        assert response.status_code == 200
        data = response.json()
        assert [row["id"] for row in data] == ["ex-old", "ex-new"]


class TestListExchangesStorageFailure:
    async def test_storage_exception_returns_500(self) -> None:
        """When storage.read_index() raises, the endpoint returns 500 with a structured error."""
        from unittest.mock import AsyncMock

        from manicure.storage import get_storage

        broken_backend = AsyncMock()
        broken_backend.read_index.side_effect = RuntimeError("disk on fire")

        app = create_app()
        app.dependency_overrides[get_storage] = lambda: broken_backend

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            response = await ac.get("/api/exchanges")

        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        assert "Failed to read exchange index" in data["detail"]


class TestGetExchange:
    async def test_get_not_found(self, client: AsyncClient) -> None:
        response = await client.get("/api/exchanges/nonexistent")
        assert response.status_code == 404

    async def test_get_existing(self, client: AsyncClient) -> None:
        from manicure.storage import get_storage

        storage = await get_storage()
        entry = _make_index_entry()
        ir = _make_ir()
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        artifacts = ExchangeArtifacts(request_raw=raw, request_ir=ir)

        await storage.append_index(entry)
        await storage.write_exchange("ex-001", artifacts)

        response = await client.get("/api/exchanges/ex-001")
        assert response.status_code == 200
        data = response.json()
        assert data["request_ir"]["model"] == "anthropic/claude-sonnet-4-20250514"
        assert data["request_curated_ir"] is None
        assert data["response_ir"] is None

    async def test_get_existing_surfaces_curated_ir(self, client: AsyncClient) -> None:
        """When a curated IR was persisted (pipeline or breakpoint edit), the
        route must surface it so the UI can show what was actually sent.

        Regression: the route previously dropped request_curated_ir on the
        floor, so edits made at a breakpoint were invisible in the UI even
        though they were correctly written to disk.
        """
        from manicure.storage import get_storage

        storage = await get_storage()
        entry = _make_index_entry()
        ir = _make_ir()
        # Simulate a user edit: curated carries a different message body.
        curated_ir = ir.model_copy(
            update={
                "messages": [
                    Message(role="user", content=[TextBlock(text="edited")]),
                ],
            }
        )
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        artifacts = ExchangeArtifacts(
            request_raw=raw,
            request_ir=ir,
            request_curated_ir=curated_ir,
        )

        await storage.append_index(entry)
        await storage.write_exchange("ex-001", artifacts)

        response = await client.get("/api/exchanges/ex-001")
        assert response.status_code == 200
        data = response.json()
        assert data["request_ir"]["messages"][0]["content"][0]["text"] == "hi"
        assert data["request_curated_ir"] is not None
        assert (
            data["request_curated_ir"]["messages"][0]["content"][0]["text"] == "edited"
        )


# ── Pipeline tokens (lazy recount) ────────────────────────────────


class _CountingStub:
    """Counter test double. Returns a preset value and tracks call count."""

    def __init__(self, value: int | None = 42) -> None:
        self.value = value
        self.calls = 0

    async def count(self, payload: bytes, auth_headers: dict[str, str]) -> int | None:
        self.calls += 1
        return self.value


class _SeqCountingStub:
    """Counter that returns values in call order; raises if exhausted.

    Used for mixed-result tests where the two-call path must see
    different values per side (e.g. (42, None) to exercise the
    partial-stamp guard).
    """

    def __init__(self, values: list[int | None]) -> None:
        self._values = list(values)
        self._idx = 0
        self.calls = 0

    async def count(self, payload: bytes, auth_headers: dict[str, str]) -> int | None:
        self.calls += 1
        value = self._values[self._idx]
        self._idx += 1
        return value


async def _seed_pipeline_entry(
    *,
    exchange_id: str = "ex-pipe",
    tokens_before: int | None = None,
    tokens_after: int | None = None,
    curated_differs: bool = False,
) -> None:
    """Write an index entry with a pipeline record and matching artifacts.

    ``curated_differs=True`` stores a curated IR that structurally
    diverges from the original; the endpoint takes the two-count path
    in that case. Otherwise curated_ir is omitted and one round-trip
    covers both sides.
    """
    from manicure.storage import get_storage

    storage = await get_storage()
    entry = _make_index_entry(exchange_id).model_copy(
        update={
            "pipeline": PipelineStats(
                chars_before=100,
                chars_after=80,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
            ),
        }
    )
    ir = _make_ir()
    raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
    curated_ir: InternalRequest | None = None
    if curated_differs:
        curated_ir = ir.model_copy(
            update={
                "messages": [
                    Message(role="user", content=[TextBlock(text="edited")]),
                ],
            }
        )
    artifacts = ExchangeArtifacts(
        request_raw=raw,
        request_ir=ir,
        request_curated_ir=curated_ir,
    )
    await storage.append_index(entry)
    await storage.write_exchange(exchange_id, artifacts)


class TestGetPipelineTokens:
    async def test_404_when_exchange_missing(self, client: AsyncClient) -> None:
        response = await client.get("/api/exchanges/nonexistent/pipeline_tokens")
        assert response.status_code == 404

    async def test_404_when_no_pipeline(self, client: AsyncClient) -> None:
        """A row without overrides has pipeline=None; nothing to count twice."""
        from manicure.storage import get_storage

        storage = await get_storage()
        await storage.append_index(_make_index_entry("ex-nopipe"))

        response = await client.get("/api/exchanges/ex-nopipe/pipeline_tokens")
        assert response.status_code == 404

    async def test_returns_cached_without_calling_counter(
        self, client: AsyncClient
    ) -> None:
        """Already-stamped rows short-circuit without touching the counter."""
        from manicure import counting

        stub = _CountingStub(value=9999)
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await _seed_pipeline_entry(tokens_before=111, tokens_after=88)

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": 111,
            "tokens_after": 88,
            "reason": None,
        }
        assert stub.calls == 0

    async def test_first_call_stamps_and_returns(self, client: AsyncClient) -> None:
        """First visit lazily computes, returns, and writes back to the index."""
        from manicure import counting
        from manicure.storage import get_storage

        stub = _CountingStub(value=42)
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await _seed_pipeline_entry()

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        # curated IR absent → single round-trip, both sides collapse to 42.
        assert response.json() == {
            "tokens_before": 42,
            "tokens_after": 42,
            "reason": None,
        }
        assert stub.calls == 1

        # Persisted: re-reading returns the stamped values without another
        # counter hit.
        storage = await get_storage()
        stored = await storage.read_index_entry("ex-pipe")
        assert stored is not None
        assert stored.pipeline is not None
        assert stored.pipeline.tokens_before == 42
        assert stored.pipeline.tokens_after == 42

        # And a second endpoint call is pure cache.
        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert stub.calls == 1

    async def test_first_call_two_roundtrips_when_curated_differs(
        self, client: AsyncClient
    ) -> None:
        """Curated IR structurally differs → counter fires for both sides."""
        from manicure import counting

        stub = _CountingStub(value=7)
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await _seed_pipeline_entry(curated_differs=True)

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": 7,
            "tokens_after": 7,
            "reason": None,
        }
        assert stub.calls == 2

    async def test_no_counter_returns_nulls(self, client: AsyncClient) -> None:
        """Addon not initialized: endpoint gracefully degrades with a reason."""
        from manicure import counting

        counting.set_recent_auth({"x-api-key": "sk-test"})
        # counter stays None (autouse fixture cleared it).

        await _seed_pipeline_entry()

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": None,
            "tokens_after": None,
            "reason": "counter_unavailable",
        }

    async def test_no_recent_auth_returns_nulls(self, client: AsyncClient) -> None:
        """Counter registered but no live flow observed: null with no_auth reason."""
        from manicure import counting

        stub = _CountingStub()
        counting.set_counter(stub)  # type: ignore[arg-type]
        # recent_auth stays None.

        await _seed_pipeline_entry()

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": None,
            "tokens_after": None,
            "reason": "no_auth",
        }
        assert stub.calls == 0

    async def test_counter_failure_returns_nulls_without_persisting(
        self, client: AsyncClient
    ) -> None:
        """Counter returns None: endpoint yields nulls and leaves the row
        eligible for retry (no sticky null stamp)."""
        from manicure import counting
        from manicure.storage import get_storage

        stub = _CountingStub(value=None)
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await _seed_pipeline_entry()

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": None,
            "tokens_after": None,
            "reason": "counter_failed",
        }
        # Row must remain null-null so a future call with a working
        # counter can still stamp it. If we had written None-None back,
        # the "already stamped" short-circuit would trap the row.
        storage = await get_storage()
        stored = await storage.read_index_entry("ex-pipe")
        assert stored is not None
        assert stored.pipeline is not None
        assert stored.pipeline.tokens_before is None
        assert stored.pipeline.tokens_after is None

    async def test_partial_before_counter_result_does_not_persist(
        self, client: AsyncClient
    ) -> None:
        """Mixed (42, None): caller sees the partial values, row stays null-null.

        The old guard persisted any row with at least one real number,
        which turned (42, None) into a sticky stamp — the next open
        would hit the "already stamped" short-circuit and never retry
        the failed side. Now the AND guard leaves the row alone so a
        future call (with a working counter) can stamp both sides.
        """
        from manicure import counting
        from manicure.storage import get_storage

        stub = _SeqCountingStub([42, None])
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        # curated_differs → two-call path, so the stub's two values land
        # on distinct sides.
        await _seed_pipeline_entry(curated_differs=True)

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": 42,
            "tokens_after": None,
            "reason": "counter_failed",
        }
        assert stub.calls == 2

        # Row must stay null-null so the next open retries instead of
        # short-circuiting on the partial stamp.
        storage = await get_storage()
        stored = await storage.read_index_entry("ex-pipe")
        assert stored is not None
        assert stored.pipeline is not None
        assert stored.pipeline.tokens_before is None
        assert stored.pipeline.tokens_after is None

    async def test_partial_after_counter_result_does_not_persist(
        self, client: AsyncClient
    ) -> None:
        """Mirror of the (42, None) case: (None, 42) is also a failure."""
        from manicure import counting
        from manicure.storage import get_storage

        stub = _SeqCountingStub([None, 42])
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await _seed_pipeline_entry(curated_differs=True)

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": None,
            "tokens_after": 42,
            "reason": "counter_failed",
        }
        assert stub.calls == 2

        storage = await get_storage()
        stored = await storage.read_index_entry("ex-pipe")
        assert stored is not None
        assert stored.pipeline is not None
        assert stored.pipeline.tokens_before is None
        assert stored.pipeline.tokens_after is None

    async def test_artifact_missing_returns_reason(self, client: AsyncClient) -> None:
        """Index entry present but artifacts gone from disk → artifact_missing.

        Simulated by writing only the index row (no ``write_exchange``
        call), so ``storage.read_exchange`` raises FileNotFoundError
        inside the endpoint.
        """
        from manicure import counting
        from manicure.storage import get_storage

        stub = _CountingStub(value=42)
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        storage = await get_storage()
        entry = _make_index_entry("ex-orphan").model_copy(
            update={
                "pipeline": PipelineStats(
                    chars_before=100,
                    chars_after=80,
                    tokens_before=None,
                    tokens_after=None,
                ),
            }
        )
        await storage.append_index(entry)

        response = await client.get("/api/exchanges/ex-orphan/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": None,
            "tokens_after": None,
            "reason": "artifact_missing",
        }
        assert stub.calls == 0

    async def test_concurrent_callers_share_one_counter_call(
        self, client: AsyncClient
    ) -> None:
        """Two simultaneous opens of the same exchange trigger exactly one
        count_tokens round-trip; the second waits for the first and
        returns the newly-persisted values."""
        from manicure import counting

        # Gate the stub so both requests overlap inside the lock. Without
        # the event, the first call would complete before the second
        # even reaches _lock_for and we would not actually exercise the
        # dedupe path.
        gate = asyncio.Event()

        class _GatedStub:
            def __init__(self) -> None:
                self.calls = 0

            async def count(
                self, payload: bytes, auth_headers: dict[str, str]
            ) -> int | None:
                self.calls += 1
                await gate.wait()
                return 55

        stub = _GatedStub()
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await _seed_pipeline_entry()

        req_a = asyncio.create_task(
            client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        )
        req_b = asyncio.create_task(
            client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        )
        # Yield so both tasks enter the endpoint and one acquires the
        # per-exchange lock before we release the gate.
        await asyncio.sleep(0.05)
        gate.set()

        resp_a, resp_b = await asyncio.gather(req_a, req_b)
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert resp_a.json() == {
            "tokens_before": 55,
            "tokens_after": 55,
            "reason": None,
        }
        assert resp_b.json() == {
            "tokens_before": 55,
            "tokens_after": 55,
            "reason": None,
        }
        assert stub.calls == 1
