import json
from typing import TYPE_CHECKING, cast

from transport_matters import broadcast
from transport_matters import exchange_recorder as recorder
from transport_matters._exchange_recorder_http_support import (
    _Flow,
    _make_ir,
    _make_response_body,
    _make_state,
    _Response,
    _SeqCounter,
)
from transport_matters.overrides import OverrideAudit, OverrideAuditEntry
from transport_matters.storage import get_storage
from transport_matters.track_manager import TrackAssignment

if TYPE_CHECKING:
    import pytest
    from mitmproxy import http

    from transport_matters.flow_state import RequestFlowState
    from transport_matters.ir import InternalResponse

pytest_plugins = ("transport_matters._exchange_recorder_http_fixtures",)


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

    monkeypatch.setattr(recorder, "persist_track_assignment", fake_track_assignment)
    events = broadcast.subscribe()

    exchange_id = await recorder.persist_http_provisional_exchange(flow, state)

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

    monkeypatch.setattr(recorder, "persist_track_assignment", fail_track_assignment)
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
    exchange_id = await recorder.persist_http_provisional_exchange(flow, state)

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
