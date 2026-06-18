"""Async boundary tests for the capabilities endpoint."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from transport_matters.capabilities import HarnessCapability

if TYPE_CHECKING:
    import pytest
    from httpx import AsyncClient


async def test_capabilities_endpoint_offloads_detection(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop_thread = threading.get_ident()
    detected_thread: dict[str, int] = {}

    def fake_detect_harnesses() -> dict[str, HarnessCapability]:
        detected_thread["id"] = threading.get_ident()
        return {
            "claude": HarnessCapability(installed=True, path="/bin/claude", version=None),
            "codex": HarnessCapability(installed=False, path=None, version=None),
        }

    monkeypatch.setattr(
        "transport_matters.api.v1.capabilities.detect_harnesses",
        fake_detect_harnesses,
    )

    response = await client.get("/api/capabilities")

    assert response.status_code == 200
    assert detected_thread["id"] != loop_thread
