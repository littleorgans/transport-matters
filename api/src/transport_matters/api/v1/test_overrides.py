"""Tests for the override API endpoints."""

import asyncio
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from transport_matters import breakpoint as bp
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
)
from transport_matters.main import create_app
from transport_matters.overrides import Override, get_store
from transport_matters.storage import init_storage, reset_storage

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
def _reset_state() -> Generator[None]:
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


_MINIMAL_IR = InternalRequest(
    model="claude-3",
    provider="anthropic",
    system=[],
    tools=[],
    messages=[Message(role="user", content=[TextBlock(text="hello")])],
    sampling=SamplingParams(max_tokens=1024),
    metadata=RequestMetadata(),
)

_IR_WITH_SYSTEM = InternalRequest(
    model="claude-3",
    provider="anthropic",
    system=[SystemPart(text="secret instructions")],
    tools=[],
    messages=[Message(role="user", content=[TextBlock(text="hello")])],
    sampling=SamplingParams(max_tokens=1024),
    metadata=RequestMetadata(),
)


class TestGetOverrides:
    async def test_empty(self, client: AsyncClient) -> None:
        response = await client.get("/api/overrides")
        assert response.status_code == 200
        data = response.json()
        assert data["overrides"] == []
        assert data["enabled"] is True

    async def test_get_is_scoped(self, client: AsyncClient) -> None:
        store = get_store()
        store.upsert(
            Override(kind="system_part_toggle", target="system:0", value=False),
            scope=("run-1", "agent-1"),
        )
        store.upsert(
            Override(kind="system_part_toggle", target="system:0", value=True),
            scope=("run-1", "agent-2"),
        )

        response = await client.get("/api/overrides?run_id=run-1&track_id=agent-1")

        assert response.status_code == 200
        data = response.json()
        assert len(data["overrides"]) == 1
        assert data["overrides"][0]["value"] is False


class TestPatchOverrides:
    async def test_upsert(self, client: AsyncClient) -> None:
        response = await client.patch(
            "/api/overrides",
            json={
                "overrides": [
                    {
                        "kind": "system_part_toggle",
                        "target": "system:0",
                        "value": False,
                    }
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["overrides"]) == 1
        assert data["enabled"] is True
        # No paused flow -> audit/curated_ir are null
        assert data["audit"] is None
        assert data["curated_ir"] is None

    async def test_upsert_with_paused_flow(self, client: AsyncClient) -> None:
        """PATCH with a paused flow returns audit and curated_ir."""
        event = asyncio.Event()
        bp._paused["flow-p"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_IR_WITH_SYSTEM,
            curated_ir=_IR_WITH_SYSTEM,
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )

        response = await client.patch(
            "/api/overrides",
            json={
                "overrides": [
                    {
                        "kind": "system_part_toggle",
                        "target": "system:0",
                        "value": False,
                    }
                ]
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["audit"] is not None
        assert data["curated_ir"] is not None
        assert data["curated_ir"]["system"] == []

    async def test_upsert_null_value_removes(self, client: AsyncClient) -> None:
        # First add an override
        await client.patch(
            "/api/overrides",
            json={
                "overrides": [
                    {
                        "kind": "system_part_toggle",
                        "target": "system:0",
                        "value": False,
                    }
                ]
            },
        )
        # Then remove it
        response = await client.patch(
            "/api/overrides",
            json={
                "overrides": [
                    {
                        "kind": "system_part_toggle",
                        "target": "system:0",
                        "value": None,
                    }
                ]
            },
        )
        assert response.status_code == 200
        assert response.json()["overrides"] == []

    async def test_upsert_is_scoped(self, client: AsyncClient) -> None:
        response = await client.patch(
            "/api/overrides?run_id=run-1&track_id=agent-1",
            json={
                "overrides": [
                    {
                        "kind": "system_part_toggle",
                        "target": "system:0",
                        "value": False,
                    }
                ]
            },
        )

        assert response.status_code == 200
        assert len(response.json()["overrides"]) == 1
        other = await client.get("/api/overrides?run_id=run-1&track_id=agent-2")
        assert other.json()["overrides"] == []

    async def test_upsert_updates_matching_paused_scope(self, client: AsyncClient) -> None:
        event = asyncio.Event()
        first = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_IR_WITH_SYSTEM,
            curated_ir=_IR_WITH_SYSTEM,
            audit=None,
            paused_at_ms=1_700_000_000_000,
            run_id="run-1",
            track_id="agent-1",
        )
        second = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_IR_WITH_SYSTEM,
            curated_ir=_IR_WITH_SYSTEM,
            audit=None,
            paused_at_ms=1_700_000_000_001,
            run_id="run-1",
            track_id="agent-2",
        )
        bp._paused["flow-1"] = first
        bp._paused["flow-2"] = second

        response = await client.patch(
            "/api/overrides?run_id=run-1&track_id=agent-2",
            json={
                "overrides": [
                    {
                        "kind": "system_part_toggle",
                        "target": "system:0",
                        "value": False,
                    }
                ]
            },
        )

        assert response.status_code == 200
        assert first.curated_ir.system == _IR_WITH_SYSTEM.system
        assert second.curated_ir.system == []


class TestDeleteOverrides:
    async def test_clear(self, client: AsyncClient) -> None:
        await client.patch(
            "/api/overrides",
            json={
                "overrides": [
                    {
                        "kind": "system_part_toggle",
                        "target": "system:0",
                        "value": False,
                    }
                ]
            },
        )
        get_store().upsert(
            Override(kind="system_part_toggle", target="system:0", value=False),
            scope=("run-1", "agent-1"),
        )

        response = await client.delete("/api/overrides")
        assert response.status_code == 204

        get_resp = await client.get("/api/overrides")
        assert get_resp.json()["overrides"] == []
        assert get_store().get_all(scope=("run-1", "agent-1")) == []

    async def test_clear_is_scoped(self, client: AsyncClient) -> None:
        store = get_store()
        store.upsert(
            Override(kind="system_part_toggle", target="system:0", value=False),
            scope=("run-1", "agent-1"),
        )
        store.upsert(
            Override(kind="system_part_toggle", target="system:0", value=False),
            scope=("run-1", "agent-2"),
        )

        response = await client.delete("/api/overrides?run_id=run-1&track_id=agent-1")

        assert response.status_code == 204
        assert get_store().get_all(scope=("run-1", "agent-1")) == []
        assert len(get_store().get_all(scope=("run-1", "agent-2"))) == 1


class TestToggle:
    async def test_toggle_flips(self, client: AsyncClient) -> None:
        response = await client.post("/api/overrides/toggle")
        assert response.status_code == 200
        assert response.json()["enabled"] is False

        response = await client.post("/api/overrides/toggle")
        assert response.json()["enabled"] is True

    async def test_toggle_is_scoped(self, client: AsyncClient) -> None:
        response = await client.post("/api/overrides/toggle?run_id=run-1&track_id=agent-1")

        assert response.status_code == 200
        assert response.json()["enabled"] is False
        assert get_store().is_enabled(scope=("run-1", "agent-1")) is False
        assert get_store().is_enabled(scope=("run-1", "agent-2")) is True

    async def test_toggle_with_paused_flow(self, client: AsyncClient) -> None:
        # Add an override first
        get_store().upsert(Override(kind="system_part_toggle", target="system:0", value=False))

        event = asyncio.Event()
        bp._paused["flow-t"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_IR_WITH_SYSTEM,
            curated_ir=_IR_WITH_SYSTEM,
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )

        response = await client.post("/api/overrides/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["audit"] is not None
        assert data["curated_ir"] is not None


class TestBypassPreview:
    """When store.enabled is False, preview returns original IR with zero-delta audit."""

    async def test_patch_bypass_returns_identity(self, client: AsyncClient) -> None:
        store = get_store()
        store.upsert(Override(kind="system_part_toggle", target="system:0", value=False))
        store.enabled = False

        event = asyncio.Event()
        bp._paused["flow-bp"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_IR_WITH_SYSTEM,
            curated_ir=_IR_WITH_SYSTEM,
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )

        response = await client.patch(
            "/api/overrides",
            json={"overrides": []},
        )
        assert response.status_code == 200
        data = response.json()
        # Overrides bypassed: system part preserved, zero delta
        assert len(data["curated_ir"]["system"]) == 1
        assert data["audit"]["chars_before"] == data["audit"]["chars_after"]
        assert data["audit"]["entries"] == []

    async def test_toggle_off_bypasses_overrides(self, client: AsyncClient) -> None:
        store = get_store()
        store.upsert(Override(kind="system_part_toggle", target="system:0", value=False))

        event = asyncio.Event()
        pf = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_IR_WITH_SYSTEM,
            curated_ir=_IR_WITH_SYSTEM,
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )
        bp._paused["flow-toff"] = pf

        # Toggle off (enabled was True)
        response = await client.post("/api/overrides/toggle")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        # System part preserved because overrides are bypassed
        assert len(data["curated_ir"]["system"]) == 1
        assert data["audit"]["entries"] == []
        # PausedFlow updated to original_ir
        assert pf.curated_ir is _IR_WITH_SYSTEM
