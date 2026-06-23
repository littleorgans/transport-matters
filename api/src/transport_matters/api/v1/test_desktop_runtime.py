"""Tests for the desktop runtime discovery API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import transport_matters.api.v1.desktop_runtime as desktop_runtime_routes
from transport_matters.desktop_runtime import (
    DesktopRuntimeDiscoveryError,
    DesktopRuntimeRecord,
    desktop_log_path,
    desktop_record_path,
    write_desktop_record,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from httpx import AsyncClient


async def test_desktop_runtime_endpoint_returns_absent_status(client: AsyncClient) -> None:
    response = await client.get("/v1/desktop-runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime"]["schemaVersion"] == 2
    assert payload["runtime"]["state"] == "absent"
    assert payload["runtime"]["channel"] == "stable"
    assert payload["runtime"]["pid"] is None


async def test_desktop_runtime_endpoint_returns_live_status(
    client: AsyncClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_dir = tmp_path / "storage"
    write_desktop_record(
        desktop_record_path(storage_dir),
        DesktopRuntimeRecord(
            channel="stable",
            pid=4321,
            proxy_port=8787,
            web_port=8788,
            log_path=str(desktop_log_path(storage_dir)),
            cwd=str(tmp_path / "workspace"),
            storage_dir=str(storage_dir),
            version="1.2.3",
        ),
    )
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        "transport_matters.desktop_runtime.wait_for_port_ready",
        lambda *_args, **_kwargs: True,
    )

    response = await client.get("/v1/desktop-runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runtime"]["state"] == "live"
    assert payload["runtime"]["apiBaseUrl"] == "http://127.0.0.1:8788"
    assert payload["runtime"]["healthUrl"] == "http://127.0.0.1:8788/health"
    assert payload["runtime"]["version"] == "1.2.3"


async def test_desktop_runtime_endpoint_maps_discovery_errors(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_unavailable(*_args: object, **_kwargs: object) -> object:
        raise DesktopRuntimeDiscoveryError(
            code="desktop_runtime_unavailable",
            message="desktop runtime record is not readable",
            details={"recordPath": "/tmp/desktop.json"},
        )

    monkeypatch.setattr(desktop_runtime_routes, "discover_desktop_runtime", raise_unavailable)

    response = await client.get("/v1/desktop-runtime")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "desktop_runtime_unavailable",
        "message": "desktop runtime record is not readable",
        "details": {"recordPath": "/tmp/desktop.json"},
    }


async def test_desktop_runtime_endpoint_maps_invalid_record_errors(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_invalid(*_args: object, **_kwargs: object) -> object:
        raise DesktopRuntimeDiscoveryError(
            code="desktop_runtime_invalid",
            message="desktop runtime record is invalid",
            details={"recordPath": "/tmp/desktop.json", "reason": "invalid_record"},
        )

    monkeypatch.setattr(desktop_runtime_routes, "discover_desktop_runtime", raise_invalid)

    response = await client.get("/v1/desktop-runtime")

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "desktop_runtime_invalid",
        "message": "desktop runtime record is invalid",
        "details": {"recordPath": "/tmp/desktop.json", "reason": "invalid_record"},
    }
