"""Shared desktop backend event helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from transport_matters.loopback import loopback_http_url
from transport_matters.workspace import workspace_id

if TYPE_CHECKING:
    from pathlib import Path


def build_backend_started_event(
    *,
    route: str,
    cwd: Path,
    resolved_storage: Path,
    web_port: int,
) -> dict[str, Any]:
    """Build the one-line startup JSON contract for the desktop canvas."""
    wid = workspace_id(cwd)
    base_url = loopback_http_url(web_port)
    route_query = urlencode(
        {
            "owner": "local",
            "workspace_hash": wid.hash,
        }
    )
    return {
        "type": "transport_matters.backend_started",
        "cwd": str(cwd),
        "workspace": {
            "slug": wid.slug,
            "hash": wid.hash,
        },
        "webPort": web_port,
        "baseUrl": base_url,
        "routeUrl": f"{base_url}/{route}?{route_query}",
        "storageDir": str(resolved_storage),
    }
