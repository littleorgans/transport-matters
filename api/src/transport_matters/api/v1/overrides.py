"""Override management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel

from transport_matters import breakpoint as bp
from transport_matters.ir import (
    InternalRequest,  # noqa: TC001 — FastAPI needs runtime access
)
from transport_matters.override_state import (
    LEGACY_SCOPE_ID,
    OverrideScope,
    normalize_scope,
)
from transport_matters.overrides import (
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


def _scope_from_params(run_id: str | None, track_id: str | None) -> OverrideScope:
    if run_id is None:
        return normalize_scope((LEGACY_SCOPE_ID, track_id or LEGACY_SCOPE_ID))
    return normalize_scope((run_id, track_id or run_id))


def _paused_scope(pf: bp.PausedFlow) -> OverrideScope:
    return _scope_from_params(pf.run_id, pf.track_id)


async def _update_scoped_paused_preview(
    scope: OverrideScope,
    *,
    explicit_scope: bool,
) -> tuple[OverrideAudit | None, InternalRequest | None]:
    """Apply current scoped overrides to the matching paused flow."""
    paused = await bp.get_paused()
    if not paused:
        return None, None

    if explicit_scope:
        pf = next(
            (
                candidate
                for candidate in paused.values()
                if _paused_scope(candidate) == scope
            ),
            None,
        )
        if pf is None:
            return None, None
    else:
        pf = next(iter(paused.values()))

    store = get_store()
    if not store.is_enabled(scope=scope):
        audit = identity_audit(pf.original_ir)
        curated_ir = pf.original_ir
    else:
        curated_ir, audit = apply_overrides(store.get_all(scope=scope), pf.original_ir)

    pf.curated_ir = curated_ir
    pf.audit = audit
    return audit, curated_ir


# ── Routes ───────────────────────────────────────────────────────


@router.get("")
async def get_overrides(
    run_id: str | None = Query(default=None),
    track_id: str | None = Query(default=None),
) -> OverrideListResponse:
    store = get_store()
    scope = _scope_from_params(run_id, track_id)
    return OverrideListResponse(
        overrides=store.get_all(scope=scope),
        enabled=store.is_enabled(scope=scope),
    )


@router.patch("")
async def patch_overrides(
    body: OverrideBatchRequest,
    run_id: str | None = Query(default=None),
    track_id: str | None = Query(default=None),
) -> OverrideMutateResponse:
    store = get_store()
    scope = _scope_from_params(run_id, track_id)
    for override in body.overrides:
        store.upsert(override, scope=scope)

    audit, curated_ir = await _update_scoped_paused_preview(
        scope,
        explicit_scope=run_id is not None or track_id is not None,
    )
    return OverrideMutateResponse(
        overrides=store.get_all(scope=scope),
        enabled=store.is_enabled(scope=scope),
        audit=audit,
        curated_ir=curated_ir,
    )


@router.delete("", status_code=204)
async def delete_overrides(
    run_id: str | None = Query(default=None),
    track_id: str | None = Query(default=None),
) -> Response:
    store = get_store()
    if run_id is None and track_id is None:
        store.clear()
    else:
        store.clear(scope=_scope_from_params(run_id, track_id))
    return Response(status_code=204)


@router.post("/toggle")
async def toggle_overrides(
    run_id: str | None = Query(default=None),
    track_id: str | None = Query(default=None),
) -> ToggleResponse:
    store = get_store()
    scope = _scope_from_params(run_id, track_id)
    store.set_enabled(not store.is_enabled(scope=scope), scope=scope)

    audit, curated_ir = await _update_scoped_paused_preview(
        scope,
        explicit_scope=run_id is not None or track_id is not None,
    )
    return ToggleResponse(
        enabled=store.is_enabled(scope=scope),
        audit=audit,
        curated_ir=curated_ir,
    )
