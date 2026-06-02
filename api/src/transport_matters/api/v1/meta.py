"""Meta endpoint: expose workspace identity and harness capabilities.

The UI uses :func:`GET /api/v1/meta` to resolve the placeholder cwd it
stamps on freshly drafted overlays. The cwd is fixed for the lifetime of
the process. It is the directory from which ``transport-matters claude``
launched, so the frontend caches this value with ``staleTime: Infinity``.

``workspace_id`` is handed through as an opaque stable string; today the
UI does not act on it, but the apply-at-intercept pipeline will key
overlays by it when that slice lands.

``harnesses`` describes executable client behavior. Upstream provider wire
semantics stay on the provider adapters and captured IR provider fields.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

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
from transport_matters.workspace import workspace_id as _workspace_id

router = APIRouter()


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


class MetaResponse(BaseModel):
    cwd: str
    workspace_id: str
    run_id: str | None
    harnesses: tuple[HarnessDescriptorResponse, ...]


@router.get("")
async def get_meta() -> MetaResponse:
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
    return MetaResponse(
        cwd=str(cwd),
        workspace_id=f"{wid.slug}/{wid.hash}",
        run_id=settings.run_id,
        harnesses=tuple(
            HarnessDescriptorResponse.from_descriptor(descriptor)
            for descriptor in list_harness_descriptors()
        ),
    )
