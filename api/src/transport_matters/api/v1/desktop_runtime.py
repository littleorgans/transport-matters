"""Desktop runtime discovery routes."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict, Field

from transport_matters.api.v1.errors import raise_api_error
from transport_matters.channel import resolve_channel_spec
from transport_matters.config import get_settings
from transport_matters.desktop_runtime import (
    DesktopRuntimeDiscoveryError,
    DesktopRuntimeState,
    desktop_runtime_status_to_json,
    discover_desktop_runtime,
)

router = APIRouter()

_DISCOVERY_ERROR_STATUS = {
    "desktop_runtime_unavailable": status.HTTP_503_SERVICE_UNAVAILABLE,
    "desktop_runtime_invalid": status.HTTP_500_INTERNAL_SERVER_ERROR,
}


class DesktopRuntimeStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal[2] = Field(alias="schemaVersion")
    state: DesktopRuntimeState
    channel: str
    instance: str
    pid: int | None
    proxy_port: int | None = Field(alias="proxyPort")
    web_port: int | None = Field(alias="webPort")
    api_base_url: str | None = Field(alias="apiBaseUrl")
    health_url: str | None = Field(alias="healthUrl")
    default_route_url: str | None = Field(alias="defaultRouteUrl")
    cwd: str | None
    storage_dir: str = Field(alias="storageDir")
    record_path: str = Field(alias="recordPath")
    log_path: str | None = Field(alias="logPath")
    started_at: str | None = Field(alias="startedAt")
    version: str | None
    reason: str | None = None


class GetDesktopRuntimeResponse(BaseModel):
    runtime: DesktopRuntimeStatusResponse


@router.get("/desktop-runtime", response_model=GetDesktopRuntimeResponse)
async def get_desktop_runtime() -> GetDesktopRuntimeResponse:
    settings = get_settings()
    channel_spec = resolve_channel_spec(settings.channel)
    cwd = settings.cwd or Path.cwd()
    try:
        runtime_status = discover_desktop_runtime(
            channel=channel_spec.id,
            storage_dir=settings.storage_dir,
            route="canvas",
            cwd=cwd,
        )
    except DesktopRuntimeDiscoveryError as exc:
        raise_api_error(
            _DISCOVERY_ERROR_STATUS[exc.code],
            exc.code,
            exc.message,
            exc.details,
        )

    return GetDesktopRuntimeResponse.model_validate(desktop_runtime_status_to_json(runtime_status))
