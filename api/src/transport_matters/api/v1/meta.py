"""Meta endpoint: expose workspace identity and harness capabilities.

The UI uses :func:`GET /api/v1/meta` to resolve the placeholder cwd it
stamps on freshly drafted overlays. The cwd is fixed for the lifetime of
the process. It is the directory from which ``transport-matters claude``
launched, so the frontend caches this value with ``staleTime: Infinity``.

``workspace_id`` is handed through as an opaque stable string; today the
UI does not act on it, but the apply-at-intercept pipeline will key
overlays by it when that slice lands.

``harnesses`` describes executable harness behavior. Upstream provider wire
semantics stay on the provider adapters and captured IR provider fields.
"""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from transport_matters.api.v1.run_storage import resolve_run_storage_or_404, run_workspace_id
from transport_matters.api.v1.session_store import optional_session_pool
from transport_matters.channel import ChannelBadge, resolve_channel_spec
from transport_matters.config import get_settings
from transport_matters.harnesses import (
    HarnessCapabilities,
    HarnessDescriptor,
    HarnessPassThroughPolicy,
    HarnessProxyMode,
    HarnessShellEnvironmentPolicy,
    HarnessTrustRequirement,
    list_harness_descriptors,
)
from transport_matters.space.store import SpaceStore
from transport_matters.transcript_denylist import TranscriptDenyRule, read_transcript_denylist
from transport_matters.workspace import workspace_id as _workspace_id

logger = logging.getLogger(__name__)

router = APIRouter()
run_router = APIRouter()


class HarnessDescriptorResponse(BaseModel):
    id: str
    display_name: str
    command_name: str
    subcommand_id: str
    binary_option: str
    disable_flag: str
    proxy_mode: HarnessProxyMode
    trust_requirement: HarnessTrustRequirement
    shell_environment_policy: HarnessShellEnvironmentPolicy
    pass_through_policy: HarnessPassThroughPolicy
    capabilities: HarnessCapabilities

    @classmethod
    def from_descriptor(cls, descriptor: HarnessDescriptor) -> HarnessDescriptorResponse:
        return cls(
            id=descriptor.id,
            display_name=descriptor.display_name,
            command_name=descriptor.command_name,
            subcommand_id=descriptor.subcommand_id,
            binary_option=descriptor.binary_option,
            disable_flag=descriptor.disable_flag,
            proxy_mode=descriptor.proxy_mode,
            trust_requirement=descriptor.trust_requirement,
            shell_environment_policy=descriptor.shell_environment_policy,
            pass_through_policy=descriptor.pass_through_policy,
            capabilities=descriptor.capabilities,
        )


class ChannelBadgeResponse(BaseModel):
    text: str
    color: str
    hex: str

    @classmethod
    def from_badge(cls, badge: ChannelBadge) -> ChannelBadgeResponse:
        return cls(text=badge.text, color=badge.color, hex=badge.hex)


class MetaResponse(BaseModel):
    cwd: str
    workspace_id: str
    run_id: str | None
    # The launch cwd's resolved Space + primary worktree, so the canvas has a
    # default spawn target. Best-effort: null when the session store is
    # unavailable (meta must stay usable in degraded/no-DB mode).
    space_id: str | None
    worktree_id: str | None
    channel: str
    channel_label: str
    channel_badge: ChannelBadgeResponse | None
    harnesses: tuple[HarnessDescriptorResponse, ...]
    transcript_denylist: tuple[TranscriptDenyRule, ...]


@router.get("")
async def get_meta(request: Request) -> MetaResponse:
    """Return the backend's resolved cwd, workspace id, and harness data.

    ``TRANSPORT_MATTERS_CWD`` (set by ``transport-matters claude`` at
    invocation time) wins over :meth:`Path.cwd` so the result reflects the user's
    launch directory even if the mitmdump process inherited a
    different cwd (e.g. launched from within ``api/``). Falls back to
    the process cwd for direct-uvicorn dev runs where the env var is
    absent.
    """
    settings = get_settings()
    cwd = (settings.cwd or Path.cwd()).resolve()
    wid = _workspace_id(cwd)
    space_id, worktree_id = await _resolve_launch_worktree(request, str(cwd))
    return _build_meta_response(
        cwd=str(cwd),
        workspace_id=f"{wid.slug}/{wid.hash}",
        run_id=settings.run_id,
        space_id=space_id,
        worktree_id=worktree_id,
    )


async def _resolve_launch_worktree(request: Request, cwd: str) -> tuple[str | None, str | None]:
    """Resolve the launch cwd's Space + primary worktree, best-effort.

    The canvas seeds its default spawn target from this (``POST /v1/runs``
    requires a worktree). Returns ``(None, None)`` when the session store is
    unavailable or resolution fails, so meta stays usable in degraded/no-DB
    mode and never fails the launch over a missing default.
    """
    pool = optional_session_pool(request)
    if pool is None:
        return (None, None)
    try:
        async with pool.connection() as conn:
            resolved = await SpaceStore(conn).resolve_session_cwd(cwd, owner="local")
    except Exception:
        logger.warning("meta launch-worktree resolution failed for %s", cwd, exc_info=True)
        return (None, None)
    return (str(resolved.space_id), str(resolved.worktree_id))


@run_router.get("")
async def get_run_meta(run_id: str, request: Request) -> MetaResponse:
    """Return the resolved identity for a run scoped API caller."""
    context = await resolve_run_storage_or_404(request, run_id)
    return _build_meta_response(
        cwd=str(context.cwd),
        workspace_id=run_workspace_id(context),
        run_id=run_id,
    )


def _build_meta_response(
    *,
    cwd: str,
    workspace_id: str,
    run_id: str | None,
    space_id: str | None = None,
    worktree_id: str | None = None,
) -> MetaResponse:
    channel_spec = resolve_channel_spec(get_settings().channel)
    return MetaResponse(
        cwd=cwd,
        workspace_id=workspace_id,
        run_id=run_id,
        space_id=space_id,
        worktree_id=worktree_id,
        channel=channel_spec.id,
        channel_label=channel_spec.label,
        channel_badge=(
            ChannelBadgeResponse.from_badge(channel_spec.badge)
            if channel_spec.badge is not None
            else None
        ),
        harnesses=tuple(
            HarnessDescriptorResponse.from_descriptor(descriptor)
            for descriptor in list_harness_descriptors()
        ),
        transcript_denylist=read_transcript_denylist().hide,
    )
