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
    SystemPart,
    TextBlock,
)
from manicure.main import create_app
from manicure.overrides import Override, get_store
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
    """Reset breakpoint and override state between tests."""
    bp.disarm()
    bp._paused.clear()
    store = get_store()
    store.clear()
    store.enabled = True
    yield
    bp.disarm()
    bp._paused.clear()
    store = get_store()
    store.clear()
    store.enabled = True


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
        event = asyncio.Event()
        bp._paused["flow-x"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]  # not accessed by the route
            event=event,
            original_ir=_MINIMAL_IR,
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


# IR with a system part that overrides can target
_IR_WITH_SYSTEM = InternalRequest(
    model="claude-3",
    provider="anthropic",
    system=[SystemPart(text="secret instructions")],
    tools=[],
    messages=[Message(role="user", content=[TextBlock(text="hello")])],
    sampling=SamplingParams(max_tokens=1024),
    metadata=RequestMetadata(),
)


class TestReAudit:
    async def test_not_found(self, client: AsyncClient) -> None:
        response = await client.post("/api/breakpoint/re-audit/nonexistent")
        assert response.status_code == 404

    async def test_re_audit_no_overrides(self, client: AsyncClient) -> None:
        """Re-audit with no overrides returns identity transform."""
        event = asyncio.Event()
        bp._paused["flow-ra"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_MINIMAL_IR,
            curated_ir=_MINIMAL_IR,
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )

        response = await client.post("/api/breakpoint/re-audit/flow-ra")
        assert response.status_code == 200
        data = response.json()
        assert data["audit"]["entries"] == []
        assert data["audit"]["chars_before"] == data["audit"]["chars_after"]
        assert data["curated_ir"]["model"] == "claude-3"

    async def test_re_audit_applies_override(self, client: AsyncClient) -> None:
        """Re-audit applies current overrides to original IR."""
        store = get_store()
        store.upsert(
            Override(kind="system_part_toggle", target="system:0", value=False)
        )

        event = asyncio.Event()
        bp._paused["flow-rule"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_IR_WITH_SYSTEM,
            curated_ir=_IR_WITH_SYSTEM,
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )

        response = await client.post("/api/breakpoint/re-audit/flow-rule")
        assert response.status_code == 200
        data = response.json()
        assert len(data["audit"]["entries"]) == 1
        # System part should be stripped
        assert data["curated_ir"]["system"] == []

    async def test_re_audit_updates_paused_flow(self, client: AsyncClient) -> None:
        """Re-audit mutates the PausedFlow curated_ir and audit in place."""
        store = get_store()
        store.upsert(
            Override(kind="system_part_toggle", target="system:0", value=False)
        )

        event = asyncio.Event()
        pf = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_IR_WITH_SYSTEM,
            curated_ir=_IR_WITH_SYSTEM,
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )
        bp._paused["flow-upd"] = pf

        await client.post("/api/breakpoint/re-audit/flow-upd")

        assert pf.audit is not None
        assert len(pf.audit.entries) == 1
        assert pf.curated_ir.system == []

    async def test_re_audit_uses_original_ir(self, client: AsyncClient) -> None:
        """Re-audit always uses original_ir, not current curated_ir."""
        stripped_ir = _IR_WITH_SYSTEM.model_copy(update={"system": []})
        event = asyncio.Event()
        bp._paused["flow-orig"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_IR_WITH_SYSTEM,
            curated_ir=stripped_ir,
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )

        # No overrides: re-audit on original_ir should restore system part
        response = await client.post("/api/breakpoint/re-audit/flow-orig")
        assert response.status_code == 200
        data = response.json()
        assert len(data["curated_ir"]["system"]) == 1
        assert data["curated_ir"]["system"][0]["text"] == "secret instructions"

    async def test_re_audit_bypass_when_disabled(self, client: AsyncClient) -> None:
        """Re-audit returns identity audit when store.enabled is False."""
        store = get_store()
        store.upsert(
            Override(kind="system_part_toggle", target="system:0", value=False)
        )
        store.enabled = False

        event = asyncio.Event()
        pf = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_IR_WITH_SYSTEM,
            curated_ir=_IR_WITH_SYSTEM,
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )
        bp._paused["flow-bypass"] = pf

        response = await client.post("/api/breakpoint/re-audit/flow-bypass")
        assert response.status_code == 200
        data = response.json()
        # Overrides bypassed: system part preserved, zero delta, no entries
        assert len(data["curated_ir"]["system"]) == 1
        assert data["audit"]["chars_before"] == data["audit"]["chars_after"]
        assert data["audit"]["entries"] == []
        # PausedFlow updated to original_ir
        assert pf.curated_ir is _IR_WITH_SYSTEM
