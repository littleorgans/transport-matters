"""Typed accessors for request state stored on mitmproxy flows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

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
_PROVISIONAL_EXCHANGE_ID_KEY = "manicure_provisional_exchange_id"
_DROPPED_KEY = "manicure_dropped"
_UNSET = object()


@dataclass(slots=True)
class RequestFlowState:
    adapter: Any
    request_ir: InternalRequest
    raw_request: bytes
    curated_request_ir: InternalRequest
    audit: OverrideAudit | None
    track_assignment: TrackAssignment | None = None
    mutated_manually: bool = False
    provisional_exchange_id: str | None = None
    """HTTP provisional exchange ID. Finalize leaves this set until flow cleanup."""
    dropped: bool = False


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
    flow.metadata[_PROVISIONAL_EXCHANGE_ID_KEY] = state.provisional_exchange_id
    flow.metadata[_DROPPED_KEY] = state.dropped
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
    provisional_exchange_id = flow.metadata.get(_PROVISIONAL_EXCHANGE_ID_KEY)
    dropped = flow.metadata.get(_DROPPED_KEY, False)
    return RequestFlowState(
        adapter=adapter,
        request_ir=request_ir,
        raw_request=raw_request,
        curated_request_ir=curated_request_ir,
        audit=audit,
        track_assignment=track_assignment,
        mutated_manually=mutated_manually,
        provisional_exchange_id=(
            provisional_exchange_id
            if isinstance(provisional_exchange_id, str)
            else None
        ),
        dropped=dropped if isinstance(dropped, bool) else False,
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
        _PROVISIONAL_EXCHANGE_ID_KEY,
        _DROPPED_KEY,
    ):
        flow.metadata.pop(key, None)


def update_request_flow_state(
    flow: http.HTTPFlow,
    *,
    curated_request_ir: InternalRequest | object = _UNSET,
    audit: OverrideAudit | None | object = _UNSET,
    track_assignment: TrackAssignment | None | object = _UNSET,
    mutated_manually: bool | None = None,
    provisional_exchange_id: str | None | object = _UNSET,
    dropped: bool | None = None,
) -> RequestFlowState | None:
    """Update the mutable request state fields for a flow."""
    state = get_request_flow_state(flow)
    if state is None:
        return None
    if curated_request_ir is not _UNSET:
        state.curated_request_ir = cast("InternalRequest", curated_request_ir)
    if audit is not _UNSET:
        state.audit = cast("OverrideAudit | None", audit)
    if track_assignment is not _UNSET:
        state.track_assignment = (
            track_assignment if isinstance(track_assignment, TrackAssignment) else None
        )
    if mutated_manually is not None:
        state.mutated_manually = mutated_manually
    if provisional_exchange_id is not _UNSET:
        state.provisional_exchange_id = cast("str | None", provisional_exchange_id)
    if dropped is not None:
        state.dropped = dropped
    if curated_request_ir is not _UNSET:
        flow.metadata[_CURATED_REQUEST_IR_KEY] = state.curated_request_ir
    if audit is not _UNSET:
        flow.metadata[_AUDIT_KEY] = state.audit
    if track_assignment is not _UNSET:
        flow.metadata[_TRACK_ASSIGNMENT_KEY] = state.track_assignment
    if mutated_manually is not None:
        flow.metadata[_MUTATED_MANUALLY_KEY] = state.mutated_manually
    if provisional_exchange_id is not _UNSET:
        flow.metadata[_PROVISIONAL_EXCHANGE_ID_KEY] = state.provisional_exchange_id
    if dropped is not None:
        flow.metadata[_DROPPED_KEY] = state.dropped
    return state
