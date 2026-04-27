"""Breakpoint API routes.

Named ``breakpoint_routes`` to avoid shadowing ``manicure.breakpoint``.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from manicure import breakpoint as bp
from manicure.adapters import get_adapter_for_provider
from manicure.adapters.anthropic import AnthropicAdapter
from manicure.codex.transport import get_codex_transport_state
from manicure.counting import get_counter
from manicure.exceptions import NotFoundError
from manicure.ir import (  # noqa: TC001 — FastAPI needs runtime access
    InternalRequest,
    Message,
    SamplingParams,
    SystemPart,
    ToolDef,
)
from manicure.override_state import LEGACY_SCOPE_ID, OverrideScope, normalize_scope
from manicure.overrides import (
    OverrideAudit,  # noqa: TC001 — FastAPI needs runtime access
    apply_overrides,
    get_store,
    identity_audit,
)
from manicure.storage.base import SpawnAnchor

logger = logging.getLogger(__name__)

router = APIRouter()


def _scope_for_paused_flow(pf: bp.PausedFlow) -> OverrideScope:
    if pf.run_id is None:
        return normalize_scope((LEGACY_SCOPE_ID, pf.track_id or LEGACY_SCOPE_ID))
    return normalize_scope((pf.run_id, pf.track_id or pf.run_id))


async def _recount_tokens(pf: bp.PausedFlow) -> int | None:
    """Fire /v1/messages/count_tokens for a paused flow's current curated IR.

    Returns None when the process-wide counter is not registered (addon
    has not initialized yet, or is already torn down), when the flow has
    no stored auth headers (legacy paused flows from before this field
    was added), or when the network call fails. Callers treat None as
    "keep the UI em dash" rather than a hard error.
    """
    counter = get_counter()
    if counter is None or not pf.auth_headers:
        return None
    if pf.original_ir.provider != "anthropic":
        return None
    try:
        return await counter.count(
            AnthropicAdapter().outbound_request(pf.curated_ir),
            pf.auth_headers,
        )
    except Exception:
        logger.exception("re-audit count_tokens failed")
        return None


class PausedFlowInfo(BaseModel):
    flow_id: str
    paused_at_ms: int


class PausedFlowDetail(BaseModel):
    """Full paused flow data for hydrating the UI after a browser refresh."""

    flow_id: str
    transport: Literal["http", "websocket"]
    run_id: str | None = None
    track_id: str | None = None
    parent_track_id: str | None = None
    track_display_name: str | None = None
    track_role: Literal["parent", "subagent"] | None = None
    spawn_anchor: SpawnAnchor | None = None
    ir: InternalRequest
    original_tools: list[ToolDef]
    original_system: list[SystemPart]
    original_messages: list[Message]
    # Pristine sampling/provider_extras from the client's request, pre-override.
    # The editor reads these as the "revert to" reference when the user resets
    # a sampling_set or provider_extras_set override, since curated_ir already
    # reflects any active overrides layered on top.
    # dict[str, object] — provider_extras is structurally opaque (provider-specific
    # JSON passthrough), so we preserve the shape without tightening it here.
    original_sampling: SamplingParams
    original_provider_extras: dict[str, object]
    audit: OverrideAudit | None
    paused_at_ms: int
    provisional_exchange_id: str | None = None
    # Authoritative count_tokens result for the curated IR, or null when
    # the count has not landed yet (fire-and-forget on pause) or failed.
    tokens_before: int | None = None


class BreakpointStatusDetail(BaseModel):
    mode: str
    paused_flows: list[PausedFlowInfo]


@router.get("/status")
async def get_status() -> BreakpointStatusDetail:
    paused = await bp.get_paused()
    return BreakpointStatusDetail(
        mode=bp.get_mode(),
        paused_flows=[
            PausedFlowInfo(flow_id=fid, paused_at_ms=pf.paused_at_ms)
            for fid, pf in paused.items()
        ],
    )


@router.get("/paused/{flow_id}")
async def get_paused_flow(flow_id: str) -> PausedFlowDetail:
    """Return the full IR and audit for a currently-paused flow.

    Used by the frontend to hydrate the breakpoint overlay after a browser
    refresh, when the SSE "paused" event has already been missed.
    """
    paused = await bp.get_paused()
    pf = paused.get(flow_id)
    if pf is None:
        raise NotFoundError(
            f"Flow {flow_id} is not paused or has already been resolved"
        )
    provisional_exchange_id = None
    if pf.transport == "websocket" and pf.flow is not None:
        state = get_codex_transport_state(pf.flow)
        if state is not None:
            provisional_exchange_id = state.provisional_exchange_id
    return PausedFlowDetail(
        flow_id=flow_id,
        transport=pf.transport,
        run_id=pf.run_id,
        track_id=pf.track_id,
        parent_track_id=pf.parent_track_id,
        track_display_name=pf.track_display_name,
        track_role=pf.track_role,
        spawn_anchor=pf.spawn_anchor,
        ir=pf.curated_ir,
        original_tools=list(pf.original_ir.tools),
        original_system=list(pf.original_ir.system),
        original_messages=list(pf.original_ir.messages),
        original_sampling=pf.original_ir.sampling,
        original_provider_extras=dict(pf.original_ir.provider_extras),
        audit=pf.audit,
        paused_at_ms=pf.paused_at_ms,
        provisional_exchange_id=provisional_exchange_id,
        tokens_before=pf.tokens_before,
    )


@router.post("/arm")
async def arm_breakpoint() -> dict[str, str]:
    bp.arm()
    return {"mode": "armed_once"}


@router.post("/disarm")
async def disarm_breakpoint() -> dict[str, str]:
    bp.disarm()
    return {"mode": "off"}


@router.post("/release/{flow_id}")
async def release_flow(flow_id: str, ir: InternalRequest) -> dict[str, str]:
    paused = await bp.get_paused()
    pf = paused.get(flow_id)
    if pf is None:
        raise NotFoundError(f"Flow {flow_id} not found or already resolved")
    if ir.provider != pf.original_ir.provider:
        raise HTTPException(
            status_code=422,
            detail=(
                "Edited request changed provider from "
                f"{pf.original_ir.provider} to {ir.provider}"
            ),
        )
    payload = _validated_release_payload(ir)
    ok = await bp.release(flow_id, ir, release_payload=payload)
    if not ok:
        raise NotFoundError(f"Flow {flow_id} not found or already resolved")
    return {"status": "released"}


@router.post("/release-unmodified/{flow_id}")
async def release_flow_unmodified(flow_id: str) -> dict[str, str]:
    paused = await bp.get_paused()
    pf = paused.get(flow_id)
    if pf is None:
        raise NotFoundError(f"Flow {flow_id} not found or already resolved")
    payload = _validated_release_payload(pf.curated_ir)
    ok = await bp.release(flow_id, release_payload=payload)
    if not ok:
        raise NotFoundError(f"Flow {flow_id} not found or already resolved")
    return {"status": "released"}


class ReAuditResponse(BaseModel):
    audit: OverrideAudit
    curated_ir: InternalRequest
    # New curated-IR token count; null when the counter is unavailable
    # or the call failed. Frontend re-renders the "before" chip as —.
    tokens_before: int | None = None


@router.post("/re-audit/{flow_id}")
async def re_audit_flow(flow_id: str) -> ReAuditResponse:
    """Re-apply current overrides to a paused flow's original IR.

    Reads the override store, applies all overrides to the original
    (pre-pipeline) IR, and updates the paused flow's curated_ir and
    audit in place. Then re-fires count_tokens so the editor's "before"
    chip reflects the new structure.
    """
    paused = await bp.get_paused()
    pf = paused.get(flow_id)
    if pf is None:
        raise NotFoundError(
            f"Flow {flow_id} is not paused or has already been resolved"
        )

    store = get_store()

    scope = _scope_for_paused_flow(pf)
    if not store.is_enabled(scope=scope):
        audit = identity_audit(pf.original_ir)
        pf.curated_ir = pf.original_ir
        pf.audit = audit
    else:
        curated_ir, audit = apply_overrides(store.get_all(scope=scope), pf.original_ir)
        pf.curated_ir = curated_ir
        pf.audit = audit

    tokens_before = await _recount_tokens(pf)
    pf.tokens_before = tokens_before

    return ReAuditResponse(
        audit=pf.audit,
        curated_ir=pf.curated_ir,
        tokens_before=tokens_before,
    )


@router.post("/drop/{flow_id}")
async def drop_flow(flow_id: str) -> dict[str, str]:
    ok = await bp.drop(flow_id)
    if not ok:
        raise NotFoundError(f"Flow {flow_id} not found or already resolved")
    return {"status": "dropped"}


def _validated_release_payload(ir: InternalRequest) -> bytes:
    try:
        adapter = get_adapter_for_provider(ir.provider)
        return adapter.outbound_request(ir)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Failed to serialize edited request: {exc}",
        ) from exc
