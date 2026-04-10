"""Breakpoint API routes.

Named ``breakpoint_routes`` to avoid shadowing ``manicure.breakpoint``.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from manicure import breakpoint as bp
from manicure.exceptions import NotFoundError
from manicure.ir import InternalRequest  # noqa: TC001 — FastAPI needs runtime access

router = APIRouter()


class PausedFlowInfo(BaseModel):
    flow_id: str
    paused_at_ms: int


class BreakpointStatusDetail(BaseModel):
    mode: str
    paused_flows: list[PausedFlowInfo]


@router.get("/status")
async def get_status() -> BreakpointStatusDetail:
    return BreakpointStatusDetail(
        mode=bp.get_mode(),
        paused_flows=[
            PausedFlowInfo(flow_id=fid, paused_at_ms=pf.paused_at_ms)
            for fid, pf in bp.get_paused().items()
        ],
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
    ok = bp.release(flow_id, ir)
    if not ok:
        raise NotFoundError(f"Flow {flow_id} not found or already resolved")
    return {"status": "released"}


@router.post("/drop/{flow_id}")
async def drop_flow(flow_id: str) -> dict[str, str]:
    ok = bp.drop(flow_id)
    if not ok:
        raise NotFoundError(f"Flow {flow_id} not found or already resolved")
    return {"status": "dropped"}
