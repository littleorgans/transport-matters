import json
import uuid
from typing import TYPE_CHECKING, cast

from transport_matters import broadcast
from transport_matters import exchange_recorder as recorder
from transport_matters._exchange_recorder_http_support import (
    _Flow,
    _make_noop_state,
    _make_state,
)
from transport_matters.storage import (
    ExchangeArtifacts,
    IndexEntry,
    StorageBackend,
    get_storage,
)
from transport_matters.track_manager import TrackAssignment

if TYPE_CHECKING:
    import pytest
    from mitmproxy import http

    from transport_matters.flow_state import RequestFlowState
    from transport_matters.ir import InternalResponse

pytest_plugins = ("transport_matters._exchange_recorder_http_fixtures",)


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

    monkeypatch.setattr(recorder, "persist_track_assignment", fake_track_assignment)
    events = broadcast.subscribe()

    exchange_id = await recorder.persist_http_provisional_exchange(flow, state)

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


async def test_provisional_exchange_skips_curated_artifacts_when_pipeline_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _make_noop_state()
    flow = cast("http.HTTPFlow", _Flow())
    monkeypatch.setattr(recorder, "persist_track_assignment", lambda *a, **k: None)

    exchange_id = await recorder.persist_http_provisional_exchange(flow, state)
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

    monkeypatch.setattr(recorder, "persist_exchange", fail_persist)
    monkeypatch.setattr(recorder, "persist_track_assignment", fail_track_assignment)

    exchange_id = await recorder.persist_http_provisional_exchange(flow, state)

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

    monkeypatch.setattr(recorder, "persist_exchange", refuse_persist)

    exchange_id = await recorder.persist_http_provisional_exchange(flow, state)

    assert exchange_id is None
    assert state.provisional_exchange_id is None
    assert events.empty()
    storage = await get_storage()
    assert await storage.read_index(limit=10, offset=0) == []
