from __future__ import annotations

from typing import TYPE_CHECKING, cast

from manicure.flow_state import (
    capture_request_flow_state,
    get_request_flow_state,
    update_request_flow_state,
)
from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
)
from manicure.overrides import OverrideAudit

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
    assert state.mutated_manually is False
    assert flow.metadata["manicure_curated_ir"] == request_ir


def test_get_request_flow_state_returns_none_when_incomplete() -> None:
    flow = cast("http.HTTPFlow", _Flow())
    flow.metadata["manicure_ir"] = _make_ir()

    assert get_request_flow_state(flow) is None


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
    assert flow.metadata["manicure_mutated_manually"] is True
