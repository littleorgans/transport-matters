"""Override management endpoints."""

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel

from transport_matters import breakpoint as bp
from transport_matters.ir import (
    InternalRequest,
)
from transport_matters.override_state import (
    OverrideScope,
    scope_from_params,
)
from transport_matters.overrides import (
    Override,
    OverrideAudit,
    apply_overrides,
    get_store,
    identity_audit,
)
from transport_matters.shared_proxy.manager import SharedProxyManager
from transport_matters.shared_proxy.models import OverrideScopePayload, OverrideSnapshotPayload

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


def _paused_scope(pf: bp.PausedFlow) -> OverrideScope:
    return scope_from_params(pf.run_id, pf.track_id)


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
            (candidate for candidate in paused.values() if _paused_scope(candidate) == scope),
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


def _snapshot_scope(scope: OverrideScope) -> OverrideSnapshotPayload:
    store = get_store()
    return OverrideSnapshotPayload(
        enabled=store.is_enabled(scope=scope),
        overrides=tuple(store.get_all(scope=scope)),
    )


def _restore_scope(scope: OverrideScope, snapshot: OverrideSnapshotPayload) -> None:
    store = get_store()
    store.clear(scope=scope)
    for override in snapshot.overrides:
        store.upsert(override, scope=scope)
    store.set_enabled(snapshot.enabled, scope=scope)


async def _sync_shared_overrides(
    request: Request,
    *,
    run_id: str | None,
    track_id: str | None,
    snapshot: OverrideSnapshotPayload,
) -> None:
    if run_id is None:
        return
    manager = getattr(request.app.state, "shared_proxy_manager", None)
    if not isinstance(manager, SharedProxyManager):
        return
    if run_id not in manager.by_run_id:
        return
    scope = OverrideScopePayload(run_id=run_id, track_id=track_id)
    await manager.set_overrides(scope, snapshot)


# ── Routes ───────────────────────────────────────────────────────


@router.get("")
async def get_overrides(
    run_id: str | None = Query(default=None),
    track_id: str | None = Query(default=None),
) -> OverrideListResponse:
    store = get_store()
    scope = scope_from_params(run_id, track_id)
    return OverrideListResponse(
        overrides=store.get_all(scope=scope),
        enabled=store.is_enabled(scope=scope),
    )


@router.patch("")
async def patch_overrides(
    body: OverrideBatchRequest,
    request: Request,
    run_id: str | None = Query(default=None),
    track_id: str | None = Query(default=None),
) -> OverrideMutateResponse:
    store = get_store()
    scope = scope_from_params(run_id, track_id)
    previous = _snapshot_scope(scope)
    try:
        for override in body.overrides:
            store.upsert(override, scope=scope)

        audit, curated_ir = await _update_scoped_paused_preview(
            scope,
            explicit_scope=run_id is not None or track_id is not None,
        )
        await _sync_shared_overrides(
            request,
            run_id=run_id,
            track_id=track_id,
            snapshot=_snapshot_scope(scope),
        )
    except Exception:
        _restore_scope(scope, previous)
        raise
    return OverrideMutateResponse(
        overrides=store.get_all(scope=scope),
        enabled=store.is_enabled(scope=scope),
        audit=audit,
        curated_ir=curated_ir,
    )


@router.delete("", status_code=204)
async def delete_overrides(
    request: Request,
    run_id: str | None = Query(default=None),
    track_id: str | None = Query(default=None),
) -> Response:
    store = get_store()
    scope = scope_from_params(run_id, track_id)
    previous = _snapshot_scope(scope)
    try:
        if run_id is None and track_id is None:
            store.clear()
        else:
            store.clear(scope=scope)
        await _sync_shared_overrides(
            request,
            run_id=run_id,
            track_id=track_id,
            snapshot=_snapshot_scope(scope),
        )
    except Exception:
        _restore_scope(scope, previous)
        raise
    return Response(status_code=204)


@router.post("/toggle")
async def toggle_overrides(
    request: Request,
    run_id: str | None = Query(default=None),
    track_id: str | None = Query(default=None),
) -> ToggleResponse:
    store = get_store()
    scope = scope_from_params(run_id, track_id)
    previous = _snapshot_scope(scope)
    try:
        store.set_enabled(not store.is_enabled(scope=scope), scope=scope)

        audit, curated_ir = await _update_scoped_paused_preview(
            scope,
            explicit_scope=run_id is not None or track_id is not None,
        )
        await _sync_shared_overrides(
            request,
            run_id=run_id,
            track_id=track_id,
            snapshot=_snapshot_scope(scope),
        )
    except Exception:
        _restore_scope(scope, previous)
        raise
    return ToggleResponse(
        enabled=store.is_enabled(scope=scope),
        audit=audit,
        curated_ir=curated_ir,
    )
