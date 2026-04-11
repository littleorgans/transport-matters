"""Tests for the breakpoint API endpoints."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from manicure import breakpoint as bp
from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from manicure.main import create_app
from manicure.storage import init_storage, reset_storage

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path


@pytest.fixture(autouse=True)
def _setup_storage(tmp_path: Path) -> Generator[None]:
    """Initialise storage with a temp dir before each test."""
    reset_storage()
    init_storage(root=tmp_path)
    yield
    reset_storage()


@pytest.fixture(autouse=True)
def _reset_breakpoint() -> Generator[None]:
    """Reset breakpoint state between tests."""
    bp.disarm()
    bp._paused.clear()
    yield
    bp.disarm()
    bp._paused.clear()


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestBreakpointStatus:
    async def test_status_initial(self, client: AsyncClient) -> None:
        response = await client.get("/api/breakpoint/status")
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "off"
        assert data["paused_flows"] == []


class TestArmDisarm:
    async def test_arm(self, client: AsyncClient) -> None:
        response = await client.post("/api/breakpoint/arm")
        assert response.status_code == 200
        assert response.json()["mode"] == "armed_once"

        status = await client.get("/api/breakpoint/status")
        assert status.json()["mode"] == "armed_once"

    async def test_disarm_after_arm(self, client: AsyncClient) -> None:
        await client.post("/api/breakpoint/arm")
        response = await client.post("/api/breakpoint/disarm")
        assert response.status_code == 200
        assert response.json()["mode"] == "off"

        status = await client.get("/api/breakpoint/status")
        assert status.json()["mode"] == "off"


class TestReleaseAndDrop:
    async def test_release_not_found(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/breakpoint/release/nonexistent",
            json={
                "model": "anthropic/claude-sonnet-4-20250514",
                "provider": "anthropic",
                "system": [],
                "tools": [],
                "messages": [
                    {"role": "user", "content": [{"type": "text", "text": "hi"}]}
                ],
                "sampling": {"max_tokens": 1024},
                "metadata": {},
            },
        )
        assert response.status_code == 404

    async def test_drop_not_found(self, client: AsyncClient) -> None:
        response = await client.post("/api/breakpoint/drop/nonexistent")
        assert response.status_code == 404


_MINIMAL_IR = InternalRequest(
    model="claude-3",
    provider="anthropic",
    system=[],
    tools=[],
    messages=[Message(role="user", content=[TextBlock(text="hello")])],
    sampling=SamplingParams(max_tokens=1024),
    metadata=RequestMetadata(),
)


class TestGetPausedFlow:
    async def test_not_found(self, client: AsyncClient) -> None:
        response = await client.get("/api/breakpoint/paused/nonexistent")
        assert response.status_code == 404

    async def test_returns_ir_and_audit(self, client: AsyncClient) -> None:
        """A paused flow is retrievable with correct fields."""
        # Register a paused flow directly into bp state (no real mitmproxy needed)
        event = asyncio.Event()
        bp._paused["flow-x"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]  # not accessed by the route
            event=event,
            curated_ir=_MINIMAL_IR,
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )

        response = await client.get("/api/breakpoint/paused/flow-x")
        assert response.status_code == 200
        data = response.json()
        assert data["flow_id"] == "flow-x"
        assert data["paused_at_ms"] == 1_700_000_000_000
        assert data["audit"] is None
        assert data["ir"]["model"] == "claude-3"
