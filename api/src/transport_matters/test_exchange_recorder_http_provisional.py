from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any, cast

import pytest

from transport_matters import broadcast
from transport_matters import exchange_recorder as recorder
from transport_matters.adapters.anthropic import AnthropicAdapter
from transport_matters.flow_state import RequestFlowState
from transport_matters.ir import (
    InternalRequest,
    InternalResponse,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
)
from transport_matters.overrides import OverrideAudit, OverrideAuditEntry
from transport_matters.storage import (
    ExchangeArtifacts,
    IndexEntry,
    StorageBackend,
    get_storage,
)
from transport_matters.test_exchange_recorder_support import (
    reset_exchange_recorder_runtime_state,
)
from transport_matters.track_manager import TrackAssignment

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from mitmproxy import http


class _Flow:
    def __init__(self) -> None:
        self.id = "flow-http-provisional"
        self.metadata: dict[str, object] = {}
        self.request = _Request()
        self.response: _Response | None = None


class _Request:
    def __init__(self) -> None:
        self.headers = {"x-api-key": "test-key"}


class _Response:
    def __init__(self, body: dict[str, object]) -> None:
        self.headers = {"content-type": "application/json"}
        self._text = json.dumps(body)

    def get_text(self) -> str:
        return self._text


class _SeqCounter:
    def __init__(self, values: list[int | None]) -> None:
        self._iter = iter(values)
        self.payloads: list[bytes] = []
        self.auth_headers: list[dict[str, str]] = []
        self.calls = 0

    async def count(self, payload: bytes, auth_headers: dict[str, str]) -> int | None:
        self.calls += 1
        self.payloads.append(payload)
        self.auth_headers.append(auth_headers)
        return next(self._iter)


def _make_ir(system_text: str) -> InternalRequest:
    return InternalRequest(
        model="claude-3-5-sonnet",
        provider="anthropic",
        system=[SystemPart(text=system_text)],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hello")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


def _make_state(
    *,
    provisional_exchange_id: str | None = None,
) -> RequestFlowState:
    adapter = AnthropicAdapter()
    request_ir = _make_ir("original system")
    curated_ir = _make_ir("curated system")
    return RequestFlowState(
        adapter=adapter,
        request_ir=request_ir,
        raw_request=adapter.outbound_request(request_ir),
        curated_request_ir=curated_ir,
        audit=OverrideAudit(entries=[], chars_before=100, chars_after=80),
        mutated_manually=True,
        provisional_exchange_id=provisional_exchange_id,
    )


def _make_codex_state() -> RequestFlowState:
    state = _make_state()
    state.request_ir = state.request_ir.model_copy(
        update={"model": "codex/gpt-5-codex", "provider": "codex"}
    )
    state.curated_request_ir = state.curated_request_ir.model_copy(
        update={"model": "codex/gpt-5-codex", "provider": "codex"}
    )
    request_headers = {
        "session-id": "session-1",
        "thread-id": "thread-1",
        "x-codex-turn-metadata": '{"turn_id":"turn-1"}',
    }
    state.codex_request_headers = request_headers
    return state


def _make_response_body() -> dict[str, object]:
    return {
        "id": "msg_http_finalize",
        "type": "message",
        "role": "assistant",
        "model": "claude-3-5-sonnet",
        "stop_reason": "end_turn",
        "usage": {
            "input_tokens": 25,
            "output_tokens": 150,
            "cache_read_input_tokens": 10,
            "cache_creation_input_tokens": 5,
        },
        "content": [{"type": "text", "text": "final text"}],
    }


@pytest.fixture(autouse=True)
def _reset_runtime_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
    yield from reset_exchange_recorder_runtime_state(tmp_path, monkeypatch)


async def test_persist_http_provisional_exchange_stores_and_broadcasts_pending_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state()
    flow = cast("http.HTTPFlow", _Flow())
    track_calls: list[tuple[str | None, RequestFlowState, InternalResponse | None]] = []

    def fake_track_assignment(
        run_id: str | None,
        request_state: RequestFlowState,
        res_ir: InternalResponse | None,
        *,
        exchange_id: str | None = None,
    ) -> TrackAssignment | None:
        assert exchange_id is not None
        track_calls.append((run_id, request_state, res_ir))
        return TrackAssignment(
            track_id="track-http",
            parent_track_id=None,
            track_display_name=None,
            track_role="parent",
        )

    monkeypatch.setattr(recorder, "_persist_track_assignment", fake_track_assignment)
    events = broadcast.subscribe()

    exchange_id = await recorder._persist_http_provisional_exchange(flow, state)

    assert exchange_id is not None
    assert uuid.UUID(exchange_id).version == 4
    assert state.provisional_exchange_id is None
    assert track_calls == [("run-http", state, None)]

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == exchange_id
    assert entry.res is None
    assert entry.req.system_chars == len("curated system")
    assert entry.pipeline is not None
    assert entry.pipeline.chars_before == 100
    assert entry.pipeline.chars_after == 80
    assert entry.pipeline.tokens_before is None
    assert entry.pipeline.tokens_after is None
    assert entry.track_id == "track-http"

    artifacts = await storage.read_exchange(exchange_id)
    assert artifacts.request_raw == state.raw_request
    assert artifacts.request_ir == state.request_ir
    assert artifacts.request_curated_ir == state.curated_request_ir
    assert artifacts.request_audit == state.audit
    assert artifacts.response_raw is None
    assert artifacts.response_ir is None

    event = json.loads(events.get_nowait())
    assert event["type"] == "exchange"
    assert event["id"] == exchange_id
    assert event["flow_id"] == flow.id
    assert event["res"] is None
    assert event["req"] == entry.req.model_dump(mode="json")
    assert event["pipeline"] == entry.pipeline.model_dump(mode="json")
    assert event["track_id"] == "track-http"


def _make_noop_state() -> RequestFlowState:
    """A no-op pipeline state: curated IR equals the original, wire bytes differ.

    ``raw_request`` is kept in the original (non-canonical) key order so it
    diverges from the serializer's sorted output, reproducing the case where a
    byte comparison would wrongly record a curated artifact.
    """
    adapter = AnthropicAdapter()
    request_ir = _make_ir("same system")
    wire_bytes = json.dumps(
        {
            "model": "claude-3-5-sonnet",
            "system": [{"type": "text", "text": "same system"}],
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        }
    ).encode()
    return RequestFlowState(
        adapter=adapter,
        request_ir=request_ir,
        raw_request=wire_bytes,
        curated_request_ir=request_ir,
        audit=OverrideAudit(entries=[], chars_before=100, chars_after=100),
        mutated_manually=False,
        provisional_exchange_id=None,
    )


async def test_provisional_exchange_skips_curated_artifacts_when_pipeline_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_noop_state()
    flow = cast("http.HTTPFlow", _Flow())
    monkeypatch.setattr(recorder, "_persist_track_assignment", lambda *a, **k: None)

    exchange_id = await recorder._persist_http_provisional_exchange(flow, state)
    assert exchange_id is not None

    storage = await get_storage()
    artifacts = await storage.read_exchange(exchange_id)
    # No-op pipeline: forward the original wire bytes, store no curated artifacts
    # even though the serializer would have reordered keys.
    assert artifacts.request_raw == state.raw_request
    assert artifacts.request_curated_raw is None
    assert artifacts.request_curated_ir is None


async def test_persist_http_provisional_exchange_reuses_existing_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(provisional_exchange_id="exchange-existing")
    flow = cast("http.HTTPFlow", _Flow())
    events = broadcast.subscribe()

    async def fail_persist(
        storage: StorageBackend,
        entry: IndexEntry,
        artifacts: ExchangeArtifacts,
    ) -> bool:
        raise AssertionError("idempotent path must not persist")

    def fail_track_assignment(
        run_id: str | None,
        request_state: RequestFlowState,
        res_ir: InternalResponse | None,
        *,
        exchange_id: str | None = None,
    ) -> TrackAssignment | None:
        raise AssertionError("idempotent path must not assign a track")

    monkeypatch.setattr(recorder, "_persist_exchange", fail_persist)
    monkeypatch.setattr(recorder, "_persist_track_assignment", fail_track_assignment)

    exchange_id = await recorder._persist_http_provisional_exchange(flow, state)

    assert exchange_id == "exchange-existing"
    assert events.empty()
    storage = await get_storage()
    assert await storage.read_index(limit=10, offset=0) == []


async def test_persist_http_provisional_exchange_returns_none_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state()
    flow = cast("http.HTTPFlow", _Flow())
    events = broadcast.subscribe()

    async def refuse_persist(
        storage: StorageBackend,
        entry: IndexEntry,
        artifacts: ExchangeArtifacts,
    ) -> bool:
        return False

    monkeypatch.setattr(recorder, "_persist_exchange", refuse_persist)

    exchange_id = await recorder._persist_http_provisional_exchange(flow, state)

    assert exchange_id is None
    assert state.provisional_exchange_id is None
    assert events.empty()
    storage = await get_storage()
    assert await storage.read_index(limit=10, offset=0) == []


async def test_codex_http_derivation_receives_request_header_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow = cast("http.HTTPFlow", _Flow())
    calls: list[dict[str, Any]] = []

    def fake_derive_codex_http_turn(**kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(
        "transport_matters.codex.http_derivation.derive_codex_http_turn",
        fake_derive_codex_http_turn,
    )

    fresh_state = _make_codex_state()
    cast("_Flow", flow).response = _Response(_make_response_body())

    persisted = await recorder._persist_http_exchange(flow, fresh_state, None)

    assert persisted is True
    assert calls[0]["request_headers"] == fresh_state.codex_request_headers

    provisional_state = _make_codex_state()
    exchange_id = await recorder._persist_http_provisional_exchange(flow, provisional_state)
    assert exchange_id is not None
    provisional_state.provisional_exchange_id = exchange_id

    finalized = await recorder._finalize_http_provisional_exchange(flow, provisional_state, None)

    assert finalized is True
    assert calls[1]["request_headers"] == provisional_state.codex_request_headers


async def test_finalize_http_provisional_exchange_updates_pending_row_in_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state()
    flow = cast("http.HTTPFlow", _Flow())
    track_calls: list[tuple[str | None, RequestFlowState, InternalResponse | None, str | None]] = []

    def fake_track_assignment(
        run_id: str | None,
        request_state: RequestFlowState,
        res_ir: InternalResponse | None,
        *,
        exchange_id: str | None = None,
    ) -> TrackAssignment | None:
        track_calls.append((run_id, request_state, res_ir, exchange_id))
        if res_ir is None:
            return TrackAssignment(
                track_id="track-http",
                parent_track_id=None,
                track_display_name=None,
                track_role="parent",
            )
        return TrackAssignment(
            track_id="track-final-ignored",
            parent_track_id="track-parent-ignored",
            track_display_name="ignored",
            track_role="subagent",
        )

    monkeypatch.setattr(recorder, "_persist_track_assignment", fake_track_assignment)
    events = broadcast.subscribe()

    exchange_id = await recorder._persist_http_provisional_exchange(flow, state)

    assert exchange_id is not None
    pending_event = json.loads(events.get_nowait())
    assert pending_event["res"] is None
    storage = await get_storage()
    pending_entry = await storage.read_index_entry(exchange_id)
    assert pending_entry is not None
    pending_path = pending_entry.path
    pending_ts = pending_entry.ts

    state.provisional_exchange_id = exchange_id
    state.curated_request_ir = _make_ir("curated changed before finalize")
    state.audit = OverrideAudit(
        entries=[
            OverrideAuditEntry(
                kind="system_part_text",
                target="system:0",
                applied=True,
                chars_delta=15,
                curated_value="curated changed before finalize",
            )
        ],
        chars_before=100,
        chars_after=115,
    )
    state.mutated_manually = False
    response = _Response(_make_response_body())
    cast("_Flow", flow).response = response
    counter = _SeqCounter([321, 123])

    finalized = await recorder._finalize_http_provisional_exchange(flow, state, counter)

    assert finalized is True
    assert counter.calls == 2
    assert counter.auth_headers == [{"x-api-key": "test-key"}] * 2
    assert len(track_calls) == 2
    assert track_calls[0] == ("run-http", state, None, exchange_id)
    assert track_calls[1][0] == "run-http"
    assert track_calls[1][1] is state
    assert track_calls[1][2] is not None
    assert track_calls[1][2].stop_reason == "end_turn"
    assert track_calls[1][3] == exchange_id

    finalized_entry = await storage.read_index_entry(exchange_id)
    assert finalized_entry is not None
    assert finalized_entry.id == exchange_id
    assert finalized_entry.ts == pending_ts
    assert finalized_entry.path == pending_path
    assert finalized_entry.provider == pending_entry.provider
    assert finalized_entry.model == pending_entry.model
    assert finalized_entry.track_id == "track-http"
    assert finalized_entry.parent_track_id == pending_entry.parent_track_id
    assert finalized_entry.track_display_name == pending_entry.track_display_name
    assert finalized_entry.track_role == pending_entry.track_role
    assert finalized_entry.req.system_chars == len("curated changed before finalize")
    assert finalized_entry.req.total_chars != pending_entry.req.total_chars
    assert finalized_entry.mutated_manually is False
    assert finalized_entry.res is not None
    assert finalized_entry.res.stop_reason == "end_turn"
    assert finalized_entry.res.input_tokens == 25
    assert finalized_entry.res.output_tokens == 150
    assert finalized_entry.res.cache_read_input_tokens == 10
    assert finalized_entry.res.cache_creation_input_tokens == 5
    assert finalized_entry.res.text_chars == len("final text")
    assert finalized_entry.pipeline is not None
    assert finalized_entry.pipeline.chars_before == 100
    assert finalized_entry.pipeline.chars_after == 115
    assert len(finalized_entry.pipeline.overrides_applied) == 1
    assert finalized_entry.pipeline.tokens_before == 321
    assert finalized_entry.pipeline.tokens_after == 123

    finalized_artifacts = await storage.read_exchange(exchange_id)
    assert finalized_artifacts.request_raw == state.raw_request
    assert finalized_artifacts.request_ir == state.request_ir
    assert finalized_artifacts.request_curated_raw is not None
    assert b"curated changed before finalize" in finalized_artifacts.request_curated_raw
    assert finalized_artifacts.request_curated_ir == state.curated_request_ir
    assert finalized_artifacts.request_audit == state.audit
    assert finalized_artifacts.response_raw == response.get_text().encode()
    assert finalized_artifacts.response_ir is not None
    assert finalized_artifacts.response_ir.stop_reason == "end_turn"

    final_event = json.loads(events.get_nowait())
    assert final_event["type"] == "exchange"
    assert final_event["id"] == exchange_id
    assert final_event["flow_id"] == flow.id
    assert final_event["req"] == finalized_entry.req.model_dump(mode="json")
    assert final_event["req"] != pending_event["req"]
    assert final_event["res"] == finalized_entry.res.model_dump(mode="json")
    assert final_event["pipeline"] == finalized_entry.pipeline.model_dump(mode="json")
    assert final_event["track_id"] == "track-http"
    assert events.empty()


async def test_finalize_http_provisional_exchange_returns_false_for_missing_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(provisional_exchange_id="missing-exchange")
    flow = cast("http.HTTPFlow", _Flow())
    cast("_Flow", flow).response = _Response(_make_response_body())
    events = broadcast.subscribe()

    def fail_track_assignment(
        run_id: str | None,
        request_state: RequestFlowState,
        res_ir: InternalResponse | None,
        *,
        exchange_id: str | None = None,
    ) -> TrackAssignment | None:
        raise AssertionError("missing entry path must not assign a track")

    monkeypatch.setattr(recorder, "_persist_track_assignment", fail_track_assignment)
    counter = _SeqCounter([1, 2])

    finalized = await recorder._finalize_http_provisional_exchange(flow, state, counter)

    assert finalized is False
    assert counter.calls == 0
    assert events.empty()
    storage = await get_storage()
    assert await storage.read_index(limit=10, offset=0) == []


async def test_finalize_http_provisional_exchange_skips_token_stamping_without_counter() -> None:
    state = _make_state()
    flow = cast("http.HTTPFlow", _Flow())
    exchange_id = await recorder._persist_http_provisional_exchange(flow, state)

    assert exchange_id is not None
    state.provisional_exchange_id = exchange_id
    cast("_Flow", flow).response = _Response(_make_response_body())

    finalized = await recorder._finalize_http_provisional_exchange(flow, state, None)

    assert finalized is True
    storage = await get_storage()
    finalized_entry = await storage.read_index_entry(exchange_id)
    assert finalized_entry is not None
    assert finalized_entry.res is not None
    assert finalized_entry.res.stop_reason == "end_turn"
    assert finalized_entry.pipeline is not None
    assert finalized_entry.pipeline.chars_before == 100
    assert finalized_entry.pipeline.chars_after == 80
    assert finalized_entry.pipeline.tokens_before is None
    assert finalized_entry.pipeline.tokens_after is None


async def test_delete_http_provisional_exchange_removes_pending_row_and_broadcasts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state()
    flow = cast("http.HTTPFlow", _Flow())
    exchange_id = await recorder._persist_http_provisional_exchange(flow, state)

    assert exchange_id is not None
    state.provisional_exchange_id = exchange_id
    storage = await get_storage()
    assert await storage.read_index_entry(exchange_id) is not None
    events = broadcast.subscribe()
    deleted_calls: list[tuple[str, str | None]] = []
    emit_deleted = recorder._emit_exchange_deleted

    def spy_emit_deleted(deleted_id: str, flow_id: str | None = None) -> None:
        deleted_calls.append((deleted_id, flow_id))
        emit_deleted(deleted_id, flow_id=flow_id)

    monkeypatch.setattr(recorder, "_emit_exchange_deleted", spy_emit_deleted)

    deleted = await recorder._delete_http_provisional_exchange(flow, state)

    assert deleted is True
    assert state.provisional_exchange_id is None
    assert await storage.read_index_entry(exchange_id) is None
    delete_event = json.loads(events.get_nowait())
    assert delete_event == {
        "type": "exchange_deleted",
        "id": exchange_id,
        "flow_id": flow.id,
    }
    assert deleted_calls == [(exchange_id, flow.id)]

    deleted_again = await recorder._delete_http_provisional_exchange(flow, state)

    assert deleted_again is True
    assert events.empty()
    assert deleted_calls == [(exchange_id, flow.id)]


async def test_delete_http_provisional_exchange_returns_false_on_storage_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(provisional_exchange_id="exchange-fail")
    flow = cast("http.HTTPFlow", _Flow())
    events = broadcast.subscribe()
    storage = await get_storage()

    async def raise_delete(exchange_id: str) -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(storage, "delete_exchange", raise_delete)

    deleted = await recorder._delete_http_provisional_exchange(flow, state)

    assert deleted is False
    assert state.provisional_exchange_id == "exchange-fail"
    assert events.empty()


async def test_persist_http_exchange_deletes_when_request_state_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(provisional_exchange_id="exchange-drop")
    state.dropped = True
    flow = cast("http.HTTPFlow", _Flow())
    cast("_Flow", flow).response = _Response(_make_response_body())
    calls: list[tuple[http.HTTPFlow, RequestFlowState]] = []

    async def fake_delete(
        delete_flow: http.HTTPFlow,
        delete_state: RequestFlowState,
    ) -> bool:
        calls.append((delete_flow, delete_state))
        return True

    async def fail_finalize(*args: object) -> bool:
        raise AssertionError("drop path must not finalize")

    async def fail_persist(
        storage: StorageBackend,
        entry: IndexEntry,
        artifacts: ExchangeArtifacts,
    ) -> bool:
        raise AssertionError("drop path must not create a fallback exchange")

    monkeypatch.setattr(recorder, "_delete_http_provisional_exchange", fake_delete)
    monkeypatch.setattr(recorder, "_finalize_http_provisional_exchange", fail_finalize)
    monkeypatch.setattr(recorder, "_persist_exchange", fail_persist)

    persisted = await recorder._persist_http_exchange(flow, state, None)

    assert persisted is True
    assert calls == [(flow, state)]


async def test_persist_http_exchange_drop_without_provisional_skips_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state()
    state.dropped = True
    flow = cast("http.HTTPFlow", _Flow())
    cast("_Flow", flow).response = _Response(_make_response_body())
    calls: list[tuple[http.HTTPFlow, RequestFlowState]] = []

    async def fake_delete(
        delete_flow: http.HTTPFlow,
        delete_state: RequestFlowState,
    ) -> bool:
        calls.append((delete_flow, delete_state))
        return True

    async def fail_persist(
        storage: StorageBackend,
        entry: IndexEntry,
        artifacts: ExchangeArtifacts,
    ) -> bool:
        raise AssertionError("drop path must not create a fallback exchange")

    monkeypatch.setattr(recorder, "_delete_http_provisional_exchange", fake_delete)
    monkeypatch.setattr(recorder, "_persist_exchange", fail_persist)

    persisted = await recorder._persist_http_exchange(flow, state, None)

    assert persisted is True
    assert calls == [(flow, state)]


async def test_persist_http_exchange_finalizes_existing_provisional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(provisional_exchange_id="exchange-finalize")
    flow = cast("http.HTTPFlow", _Flow())
    cast("_Flow", flow).response = _Response(_make_response_body())
    counter = _SeqCounter([1, 2])
    calls: list[tuple[http.HTTPFlow, RequestFlowState, object | None]] = []

    async def fake_finalize(
        finalize_flow: http.HTTPFlow,
        finalize_state: RequestFlowState,
        token_counter: object | None,
    ) -> bool:
        calls.append((finalize_flow, finalize_state, token_counter))
        return True

    async def fail_persist(
        storage: StorageBackend,
        entry: IndexEntry,
        artifacts: ExchangeArtifacts,
    ) -> bool:
        raise AssertionError("finalized provisional must not create duplicate row")

    monkeypatch.setattr(recorder, "_finalize_http_provisional_exchange", fake_finalize)
    monkeypatch.setattr(recorder, "_persist_exchange", fail_persist)

    persisted = await recorder._persist_http_exchange(flow, state, counter)

    assert persisted is True
    assert calls == [(flow, state, counter)]


async def test_persist_http_exchange_falls_back_when_finalize_misses_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_state(provisional_exchange_id="exchange-missing")
    flow = cast("http.HTTPFlow", _Flow())
    cast("_Flow", flow).response = _Response(_make_response_body())
    calls: list[tuple[http.HTTPFlow, RequestFlowState, object | None]] = []

    async def fake_finalize(
        finalize_flow: http.HTTPFlow,
        finalize_state: RequestFlowState,
        token_counter: object | None,
    ) -> bool:
        calls.append((finalize_flow, finalize_state, token_counter))
        return False

    monkeypatch.setattr(recorder, "_finalize_http_provisional_exchange", fake_finalize)

    persisted = await recorder._persist_http_exchange(flow, state, None)

    assert persisted is True
    assert calls == [(flow, state, None)]
    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    assert entries[0].id != "exchange-missing"
    assert entries[0].res is not None


def test_tag_http_error_status_preserves_parsed_usage() -> None:
    import types

    from transport_matters.storage import ResStats

    flow = types.SimpleNamespace(
        response=types.SimpleNamespace(status_code=429),
    )
    parsed = ResStats(stop_reason="end_turn", input_tokens=10, output_tokens=5, text_chars=3)
    tagged = recorder._tag_http_error_status(parsed, cast("http.HTTPFlow", flow), b"{}")
    assert tagged is not None
    assert tagged.stop_reason == "http_429"
    assert tagged.input_tokens == 10
    assert tagged.output_tokens == 5


def test_tag_http_error_status_noop_on_success() -> None:
    import types

    from transport_matters.storage import ResStats

    flow = types.SimpleNamespace(response=types.SimpleNamespace(status_code=200))
    parsed = ResStats(stop_reason="end_turn", input_tokens=10)
    assert recorder._tag_http_error_status(parsed, cast("http.HTTPFlow", flow), b"{}") is parsed
