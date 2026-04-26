"""Typed accessors for request state stored on mitmproxy flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from manicure.track_manager import TrackAssignment

if TYPE_CHECKING:
    from mitmproxy import http

    from manicure.ir import InternalRequest
    from manicure.overrides import OverrideAudit


_ADAPTER_KEY = "manicure_adapter"
_REQUEST_IR_KEY = "manicure_ir"
_RAW_REQUEST_KEY = "manicure_raw_req"
_CURATED_REQUEST_IR_KEY = "manicure_curated_ir"
_AUDIT_KEY = "manicure_audit"
_MUTATED_MANUALLY_KEY = "manicure_mutated_manually"
_TRACK_ASSIGNMENT_KEY = "manicure_track_assignment"
_TRACK_ASSIGNMENT_UNSET = object()


@dataclass(slots=True)
class RequestFlowState:
    adapter: Any
    request_ir: InternalRequest
    raw_request: bytes
    curated_request_ir: InternalRequest
    audit: OverrideAudit | None
    track_assignment: TrackAssignment | None = None
    mutated_manually: bool = False


def capture_request_flow_state(
    flow: http.HTTPFlow,
    *,
    adapter: Any,
    request_ir: InternalRequest,
    raw_request: bytes,
    curated_request_ir: InternalRequest | None = None,
    audit: OverrideAudit | None = None,
    track_assignment: TrackAssignment | None = None,
    mutated_manually: bool = False,
) -> RequestFlowState:
    """Persist the canonical request state for a flow."""
    state = RequestFlowState(
        adapter=adapter,
        request_ir=request_ir,
        raw_request=raw_request,
        curated_request_ir=curated_request_ir or request_ir,
        audit=audit,
        track_assignment=track_assignment,
        mutated_manually=mutated_manually,
    )
    flow.metadata[_ADAPTER_KEY] = state.adapter
    flow.metadata[_REQUEST_IR_KEY] = state.request_ir
    flow.metadata[_RAW_REQUEST_KEY] = state.raw_request
    flow.metadata[_CURATED_REQUEST_IR_KEY] = state.curated_request_ir
    flow.metadata[_AUDIT_KEY] = state.audit
    flow.metadata[_TRACK_ASSIGNMENT_KEY] = state.track_assignment
    flow.metadata[_MUTATED_MANUALLY_KEY] = state.mutated_manually
    return state


def get_request_flow_state(flow: http.HTTPFlow) -> RequestFlowState | None:
    """Load the canonical request state for a flow when available."""
    adapter = flow.metadata.get(_ADAPTER_KEY)
    request_ir = flow.metadata.get(_REQUEST_IR_KEY)
    raw_request = flow.metadata.get(_RAW_REQUEST_KEY)
    if adapter is None or request_ir is None or raw_request is None:
        return None
    curated_request_ir = flow.metadata.get(_CURATED_REQUEST_IR_KEY, request_ir)
    audit = flow.metadata.get(_AUDIT_KEY)
    track_assignment = flow.metadata.get(_TRACK_ASSIGNMENT_KEY)
    mutated_manually = flow.metadata.get(_MUTATED_MANUALLY_KEY, False)
    return RequestFlowState(
        adapter=adapter,
        request_ir=request_ir,
        raw_request=raw_request,
        curated_request_ir=curated_request_ir,
        audit=audit,
        track_assignment=track_assignment,
        mutated_manually=mutated_manually,
    )


def clear_request_flow_state(flow: http.HTTPFlow) -> None:
    """Remove any previously captured request state from a flow."""
    for key in (
        _ADAPTER_KEY,
        _REQUEST_IR_KEY,
        _RAW_REQUEST_KEY,
        _CURATED_REQUEST_IR_KEY,
        _AUDIT_KEY,
        _TRACK_ASSIGNMENT_KEY,
        _MUTATED_MANUALLY_KEY,
    ):
        flow.metadata.pop(key, None)


def update_request_flow_state(
    flow: http.HTTPFlow,
    *,
    curated_request_ir: InternalRequest,
    audit: OverrideAudit | None,
    track_assignment: TrackAssignment | None | object = _TRACK_ASSIGNMENT_UNSET,
    mutated_manually: bool | None = None,
) -> RequestFlowState | None:
    """Update the mutable request state fields for a flow."""
    state = get_request_flow_state(flow)
    if state is None:
        return None
    state.curated_request_ir = curated_request_ir
    state.audit = audit
    if track_assignment is not _TRACK_ASSIGNMENT_UNSET:
        state.track_assignment = (
            track_assignment if isinstance(track_assignment, TrackAssignment) else None
        )
    if mutated_manually is not None:
        state.mutated_manually = mutated_manually
    flow.metadata[_CURATED_REQUEST_IR_KEY] = state.curated_request_ir
    flow.metadata[_AUDIT_KEY] = state.audit
    if track_assignment is not _TRACK_ASSIGNMENT_UNSET:
        flow.metadata[_TRACK_ASSIGNMENT_KEY] = state.track_assignment
    if mutated_manually is not None:
        flow.metadata[_MUTATED_MANUALLY_KEY] = state.mutated_manually
    return state
