"""Breakpoint API routes.

Named ``breakpoint_routes`` to avoid shadowing ``manicure.breakpoint``.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from manicure import breakpoint as bp
from manicure.exceptions import NotFoundError
from manicure.ir import (  # noqa: TC001 — FastAPI needs runtime access
    InternalRequest,
    Message,
    SystemPart,
    ToolDef,
)
from manicure.overrides import (
    OverrideAudit,  # noqa: TC001 — FastAPI needs runtime access
    apply_overrides,
    get_store,
    identity_audit,
)

router = APIRouter()


class PausedFlowInfo(BaseModel):
    flow_id: str
    paused_at_ms: int


class PausedFlowDetail(BaseModel):
    """Full paused flow data for hydrating the UI after a browser refresh."""

    flow_id: str
    ir: InternalRequest
    original_tools: list[ToolDef]
    original_system: list[SystemPart]
    original_messages: list[Message]
    audit: OverrideAudit | None
    paused_at_ms: int


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
    return PausedFlowDetail(
        flow_id=flow_id,
        ir=pf.curated_ir,
        original_tools=list(pf.original_ir.tools),
        original_system=list(pf.original_ir.system),
        original_messages=list(pf.original_ir.messages),
        audit=pf.audit,
        paused_at_ms=pf.paused_at_ms,
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
    ok = await bp.release(flow_id, ir)
    if not ok:
        raise NotFoundError(f"Flow {flow_id} not found or already resolved")
    return {"status": "released"}


@router.post("/release-unmodified/{flow_id}")
async def release_flow_unmodified(flow_id: str) -> dict[str, str]:
    ok = await bp.release(flow_id)
    if not ok:
        raise NotFoundError(f"Flow {flow_id} not found or already resolved")
    return {"status": "released"}


class ReAuditResponse(BaseModel):
    audit: OverrideAudit
    curated_ir: InternalRequest


@router.post("/re-audit/{flow_id}")
async def re_audit_flow(flow_id: str) -> ReAuditResponse:
    """Re-apply current overrides to a paused flow's original IR.

    Reads the override store, applies all overrides to the original
    (pre-pipeline) IR, and updates the paused flow's curated_ir and
    audit in place.
    """
    paused = await bp.get_paused()
    pf = paused.get(flow_id)
    if pf is None:
        raise NotFoundError(
            f"Flow {flow_id} is not paused or has already been resolved"
        )

    store = get_store()

    if not store.enabled:
        audit = identity_audit(pf.original_ir)
        pf.curated_ir = pf.original_ir
        pf.audit = audit
        return ReAuditResponse(audit=audit, curated_ir=pf.original_ir)

    curated_ir, audit = apply_overrides(store.get_all(), pf.original_ir)

    pf.curated_ir = curated_ir
    pf.audit = audit

    return ReAuditResponse(audit=audit, curated_ir=curated_ir)


@router.post("/drop/{flow_id}")
async def drop_flow(flow_id: str) -> dict[str, str]:
    ok = await bp.drop(flow_id)
    if not ok:
        raise NotFoundError(f"Flow {flow_id} not found or already resolved")
    return {"status": "dropped"}
