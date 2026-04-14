"""Override management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel

from manicure import breakpoint as bp
from manicure.ir import InternalRequest  # noqa: TC001 — FastAPI needs runtime access
from manicure.overrides import (
    Override,
    OverrideAudit,  # noqa: TC001 — FastAPI needs runtime access
    apply_overrides,
    get_store,
    identity_audit,
)

router = APIRouter()


# ── Response models ──────────────────────────────────────────────


class OverrideListResponse(BaseModel):
    overrides: list[Override]
    enabled: bool


class OverrideMutateResponse(BaseModel):
    overrides: list[Override]
    enabled: bool
    audit: OverrideAudit | None
    curated_ir: InternalRequest | None


class ToggleResponse(BaseModel):
    enabled: bool
    audit: OverrideAudit | None
    curated_ir: InternalRequest | None


class OverrideBatchRequest(BaseModel):
    overrides: list[Override]


# ── Helpers ──────────────────────────────────────────────────────


async def _update_paused_preview() -> tuple[
    OverrideAudit | None, InternalRequest | None
]:
    """Apply current overrides to the first paused flow and update it in place.

    Mutates the paused flow's ``curated_ir`` and ``audit`` so subsequent
    requests (GET paused, re-audit) reflect the latest state. Returns
    ``(None, None)`` when no flow is paused.
    """
    paused = await bp.get_paused()
    if not paused:
        return None, None

    store = get_store()
    pf = next(iter(paused.values()))

    if not store.enabled:
        audit = identity_audit(pf.original_ir)
        curated_ir = pf.original_ir
    else:
        curated_ir, audit = apply_overrides(store.get_all(), pf.original_ir)

    pf.curated_ir = curated_ir
    pf.audit = audit
    return audit, curated_ir


# ── Routes ───────────────────────────────────────────────────────


@router.get("")
async def get_overrides() -> OverrideListResponse:
    store = get_store()
    return OverrideListResponse(
        overrides=store.get_all(),
        enabled=store.enabled,
    )


@router.patch("")
async def patch_overrides(body: OverrideBatchRequest) -> OverrideMutateResponse:
    store = get_store()
    for override in body.overrides:
        store.upsert(override)

    audit, curated_ir = await _update_paused_preview()
    return OverrideMutateResponse(
        overrides=store.get_all(),
        enabled=store.enabled,
        audit=audit,
        curated_ir=curated_ir,
    )


@router.delete("", status_code=204)
async def delete_overrides() -> Response:
    get_store().clear()
    return Response(status_code=204)


@router.post("/toggle")
async def toggle_overrides() -> ToggleResponse:
    store = get_store()
    store.enabled = not store.enabled

    audit, curated_ir = await _update_paused_preview()
    return ToggleResponse(
        enabled=store.enabled,
        audit=audit,
        curated_ir=curated_ir,
    )
