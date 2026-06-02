from typing import TYPE_CHECKING, cast

from transport_matters.flow_state import (
    capture_request_flow_state,
    get_request_flow_state,
    snapshot_codex_http_request_headers,
    update_request_flow_state,
)
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
)
from transport_matters.overrides import OverrideAudit
from transport_matters.track_manager import TrackAssignment

if TYPE_CHECKING:
    from mitmproxy import http


class _Flow:
    def __init__(self) -> None:
        self.metadata: dict[str, object] = {}


def _make_ir(system_text: str = "original") -> InternalRequest:
    return InternalRequest(
        model="claude-3",
        provider="anthropic",
        system=[SystemPart(text=system_text)],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hello")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


def test_capture_request_flow_state_sets_defaults() -> None:
    flow = cast("http.HTTPFlow", _Flow())
    adapter = object()
    request_ir = _make_ir()

    state = capture_request_flow_state(
        flow,
        adapter=adapter,
        request_ir=request_ir,
        raw_request=b'{"model":"claude-3"}',
    )

    assert state.adapter is adapter
    assert state.request_ir == request_ir
    assert state.curated_request_ir == request_ir
    assert state.audit is None
    assert state.codex_request_headers == {}
    assert state.mutated_manually is False
    assert state.provisional_exchange_id is None
    assert state.dropped is False
    assert flow.metadata["transport_matters_curated_ir"] == request_ir


def test_get_request_flow_state_returns_none_when_incomplete() -> None:
    flow = cast("http.HTTPFlow", _Flow())
    flow.metadata["transport_matters_ir"] = _make_ir()

    assert get_request_flow_state(flow) is None


def test_capture_request_flow_state_snapshots_narrow_codex_headers() -> None:
    codex_headers = snapshot_codex_http_request_headers(
        {
            "Session-Id": "session-1",
            "thread-id": "thread-1",
            "x-codex-turn-metadata": '{"turn_id":"turn-1"}',
            "authorization": "Bearer secret",
            "session_id": "legacy-session",
        }
    )

    assert codex_headers == {
        "session-id": "session-1",
        "thread-id": "thread-1",
        "x-codex-turn-metadata": '{"turn_id":"turn-1"}',
    }

    flow = cast("http.HTTPFlow", _Flow())
    adapter = object()
    request_ir = _make_ir()

    capture_request_flow_state(
        flow,
        adapter=adapter,
        request_ir=request_ir,
        raw_request=b"raw",
        codex_request_headers=codex_headers,
    )

    state = get_request_flow_state(flow)
    assert state is not None
    assert state.codex_request_headers == codex_headers


def test_update_request_flow_state_rewrites_mutable_fields() -> None:
    flow = cast("http.HTTPFlow", _Flow())
    adapter = object()
    original_ir = _make_ir()
    curated_ir = _make_ir(system_text="curated")
    audit = OverrideAudit(entries=[], chars_before=10, chars_after=8)
    capture_request_flow_state(
        flow,
        adapter=adapter,
        request_ir=original_ir,
        raw_request=b"raw",
    )

    state = update_request_flow_state(
        flow,
        curated_request_ir=curated_ir,
        audit=audit,
        mutated_manually=True,
    )

    assert state is not None
    assert state.request_ir == original_ir
    assert state.curated_request_ir == curated_ir
    assert state.audit == audit
    assert state.mutated_manually is True
    assert flow.metadata["transport_matters_mutated_manually"] is True


def test_update_request_flow_state_sets_provisional_id_without_clobbering_state() -> None:
    flow = cast("http.HTTPFlow", _Flow())
    adapter = object()
    original_ir = _make_ir()
    curated_ir = _make_ir(system_text="curated")
    audit = OverrideAudit(entries=[], chars_before=10, chars_after=8)
    track_assignment = TrackAssignment(
        track_id="track-root",
        parent_track_id=None,
        track_display_name=None,
        track_role="parent",
    )
    capture_request_flow_state(
        flow,
        adapter=adapter,
        request_ir=original_ir,
        raw_request=b"raw",
        curated_request_ir=curated_ir,
        audit=audit,
        track_assignment=track_assignment,
        mutated_manually=True,
    )

    state = update_request_flow_state(
        flow,
        provisional_exchange_id="exchange-provisional",
    )

    assert state is not None
    assert state.curated_request_ir == curated_ir
    assert state.audit == audit
    assert state.track_assignment == track_assignment
    assert state.mutated_manually is True
    assert state.dropped is False
    assert state.provisional_exchange_id == "exchange-provisional"
    assert flow.metadata["transport_matters_provisional_exchange_id"] == "exchange-provisional"


def test_update_request_flow_state_sets_dropped_without_clobbering_provisional_id() -> None:
    flow = cast("http.HTTPFlow", _Flow())
    adapter = object()
    request_ir = _make_ir()
    capture_request_flow_state(
        flow,
        adapter=adapter,
        request_ir=request_ir,
        raw_request=b"raw",
    )
    update_request_flow_state(flow, provisional_exchange_id="exchange-provisional")

    state = update_request_flow_state(flow, dropped=True)

    assert state is not None
    assert state.curated_request_ir == request_ir
    assert state.audit is None
    assert state.provisional_exchange_id == "exchange-provisional"
    assert state.dropped is True
    assert flow.metadata["transport_matters_dropped"] is True


def test_update_request_flow_state_can_clear_provisional_id() -> None:
    flow = cast("http.HTTPFlow", _Flow())
    adapter = object()
    request_ir = _make_ir()
    capture_request_flow_state(
        flow,
        adapter=adapter,
        request_ir=request_ir,
        raw_request=b"raw",
    )
    update_request_flow_state(flow, provisional_exchange_id="exchange-provisional")

    state = update_request_flow_state(flow, provisional_exchange_id=None)

    assert state is not None
    assert state.provisional_exchange_id is None
    assert flow.metadata["transport_matters_provisional_exchange_id"] is None
