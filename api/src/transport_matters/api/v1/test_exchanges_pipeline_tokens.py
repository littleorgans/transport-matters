"""Tests for the exchanges pipeline token endpoint."""

import asyncio
import gc
from typing import TYPE_CHECKING
from unittest.mock import patch

from transport_matters.storage.base import IndexEntry, PipelineStats

from .test_exchanges_support import (
    CountingStub,
    SeqCountingStub,
    make_index_entry,
    seed_pipeline_entry,
)

if TYPE_CHECKING:
    from httpx import AsyncClient


class TestGetPipelineTokens:
    async def test_404_when_exchange_missing(self, client: AsyncClient) -> None:
        response = await client.get("/api/exchanges/nonexistent/pipeline_tokens")
        assert response.status_code == 404

    async def test_404_when_no_pipeline(self, client: AsyncClient) -> None:
        """A row without overrides has pipeline=None; nothing to count twice."""
        from transport_matters.storage import get_storage

        storage = await get_storage()
        await storage.append_index(make_index_entry("ex-nopipe"))

        response = await client.get("/api/exchanges/ex-nopipe/pipeline_tokens")
        assert response.status_code == 404

    async def test_non_anthropic_provider_returns_unsupported_reason(
        self, client: AsyncClient
    ) -> None:
        await seed_pipeline_entry(
            provider="codex",
            model="codex/gpt-5-codex",
        )

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": None,
            "tokens_after": None,
            "reason": "unsupported_provider",
        }

    async def test_returns_cached_without_calling_counter(self, client: AsyncClient) -> None:
        """Already stamped rows short circuit without touching the counter."""
        from transport_matters import counting

        stub = CountingStub(value=9999)
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await seed_pipeline_entry(tokens_before=111, tokens_after=88)

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
        from transport_matters import counting
        from transport_matters.storage import get_storage

        stub = CountingStub(value=42)
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await seed_pipeline_entry()

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": 42,
            "tokens_after": 42,
            "reason": None,
        }
        assert stub.calls == 1

        storage = await get_storage()
        stored = await storage.read_index_entry("ex-pipe")
        assert stored is not None
        assert stored.pipeline is not None
        assert stored.pipeline.tokens_before == 42
        assert stored.pipeline.tokens_after == 42

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert stub.calls == 1

    async def test_lazy_recount_lock_is_released_after_request(self, client: AsyncClient) -> None:
        """Per-exchange recount locks must not accumulate after the request."""
        from transport_matters import counting
        from transport_matters.api.v1 import exchanges

        exchanges._compute_locks.clear()
        stub = CountingStub(value=42)
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await seed_pipeline_entry()

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        gc.collect()

        assert response.status_code == 200
        assert "ex-pipe" not in exchanges._compute_locks

    async def test_first_call_two_roundtrips_when_curated_differs(
        self, client: AsyncClient
    ) -> None:
        """Curated IR structurally differs, so the counter fires for both sides."""
        from transport_matters import counting

        stub = CountingStub(value=7)
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await seed_pipeline_entry(curated_differs=True)

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
        from transport_matters import counting

        counting.set_recent_auth({"x-api-key": "sk-test"})

        await seed_pipeline_entry()

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": None,
            "tokens_after": None,
            "reason": "counter_unavailable",
        }

    async def test_no_recent_auth_returns_nulls(self, client: AsyncClient) -> None:
        """Counter registered but no live flow observed: null with no_auth reason."""
        from transport_matters import counting

        stub = CountingStub()
        counting.set_counter(stub)  # type: ignore[arg-type]

        await seed_pipeline_entry()

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
        """Counter returns None, so the row stays eligible for retry."""
        from transport_matters import counting
        from transport_matters.storage import get_storage

        stub = CountingStub(value=None)
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await seed_pipeline_entry()

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": None,
            "tokens_after": None,
            "reason": "counter_failed",
        }
        storage = await get_storage()
        stored = await storage.read_index_entry("ex-pipe")
        assert stored is not None
        assert stored.pipeline is not None
        assert stored.pipeline.tokens_before is None
        assert stored.pipeline.tokens_after is None

    async def test_partial_before_counter_result_does_not_persist(
        self, client: AsyncClient
    ) -> None:
        """Mixed (42, None): caller sees the partial values and row stays null-null."""
        from transport_matters import counting
        from transport_matters.storage import get_storage

        stub = SeqCountingStub([42, None])
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await seed_pipeline_entry(curated_differs=True)

        response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
        assert response.status_code == 200
        assert response.json() == {
            "tokens_before": 42,
            "tokens_after": None,
            "reason": "counter_failed",
        }
        assert stub.calls == 2

        storage = await get_storage()
        stored = await storage.read_index_entry("ex-pipe")
        assert stored is not None
        assert stored.pipeline is not None
        assert stored.pipeline.tokens_before is None
        assert stored.pipeline.tokens_after is None

    async def test_partial_after_counter_result_does_not_persist(self, client: AsyncClient) -> None:
        """Mirror of the (42, None) case: (None, 42) is also a failure."""
        from transport_matters import counting
        from transport_matters.storage import get_storage

        stub = SeqCountingStub([None, 42])
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await seed_pipeline_entry(curated_differs=True)

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

    async def test_failed_stamp_retries_on_next_open(self, client: AsyncClient) -> None:
        """A failed index rewrite must not make the in-memory row look stamped."""
        from transport_matters import counting
        from transport_matters.storage import get_storage
        from transport_matters.storage.disk import DiskStorageBackend

        stub = CountingStub(value=42)
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await seed_pipeline_entry()
        storage = await get_storage()
        assert isinstance(storage, DiskStorageBackend)
        original_rewrite = storage._rewrite_index
        rewrite_attempts = 0

        async def flaky_rewrite(entries: dict[str, IndexEntry]) -> None:
            nonlocal rewrite_attempts
            rewrite_attempts += 1
            if rewrite_attempts == 1:
                raise OSError("index rewrite failed")
            await original_rewrite(entries)

        with patch.object(storage, "_rewrite_index", side_effect=flaky_rewrite):
            response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
            assert response.status_code == 200
            assert response.json() == {
                "tokens_before": 42,
                "tokens_after": 42,
                "reason": None,
            }

            stored = await storage.read_index_entry("ex-pipe")
            assert stored is not None
            assert stored.pipeline is not None
            assert stored.pipeline.tokens_before is None
            assert stored.pipeline.tokens_after is None

            response = await client.get("/api/exchanges/ex-pipe/pipeline_tokens")
            assert response.status_code == 200
            assert response.json() == {
                "tokens_before": 42,
                "tokens_after": 42,
                "reason": None,
            }

        assert stub.calls == 2

        stored = await storage.read_index_entry("ex-pipe")
        assert stored is not None
        assert stored.pipeline is not None
        assert stored.pipeline.tokens_before == 42
        assert stored.pipeline.tokens_after == 42

    async def test_artifact_missing_returns_reason(self, client: AsyncClient) -> None:
        """Index entry present but artifacts gone from disk yields artifact_missing."""
        from transport_matters import counting
        from transport_matters.storage import get_storage

        stub = CountingStub(value=42)
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        storage = await get_storage()
        entry = make_index_entry("ex-orphan").model_copy(
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

    async def test_concurrent_callers_share_one_counter_call(self, client: AsyncClient) -> None:
        """Two simultaneous opens of the same exchange trigger one counter call."""
        from transport_matters import counting

        gate = asyncio.Event()

        class GatedStub:
            def __init__(self) -> None:
                self.calls = 0

            async def count(self, payload: bytes, auth_headers: dict[str, str]) -> int | None:
                self.calls += 1
                await gate.wait()
                return 55

        stub = GatedStub()
        counting.set_counter(stub)  # type: ignore[arg-type]
        counting.set_recent_auth({"x-api-key": "sk-test"})

        await seed_pipeline_entry()

        req_a = asyncio.create_task(client.get("/api/exchanges/ex-pipe/pipeline_tokens"))
        req_b = asyncio.create_task(client.get("/api/exchanges/ex-pipe/pipeline_tokens"))
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
