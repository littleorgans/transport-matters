"""Tests for the capabilities endpoint."""

from __future__ import annotations

from typing import TYPE_CHECKING

from transport_matters.capabilities import HarnessCapability

if TYPE_CHECKING:
    import pytest
    from httpx import AsyncClient


async def test_capabilities_endpoint_shape(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "transport_matters.api.v1.capabilities.detect_harnesses",
        lambda: {
            "claude": HarnessCapability(
                installed=True,
                path="/bin/claude",
                version="claude 1.2.3",
            ),
            "codex": HarnessCapability(installed=False, path=None, version=None),
        },
    )

    response = await client.get("/api/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "harnesses": {
            "claude": {
                "installed": True,
                "path": "/bin/claude",
                "version": "claude 1.2.3",
            },
            "codex": {
                "installed": False,
                "path": None,
                "version": None,
            },
        }
    }
