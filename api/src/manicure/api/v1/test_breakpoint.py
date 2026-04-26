"""Tests for the breakpoint API endpoints."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from manicure import breakpoint as bp
from manicure.codex.transport import CodexTransportState, CodexUpgradeMetadata
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
        assert data["transport"] == "http"
        assert data["paused_at_ms"] == 1_700_000_000_000
        assert data["audit"] is None
        assert data["ir"]["model"] == "claude-3"
        assert data["tokens_before"] is None

    async def test_returns_track_scope(self, client: AsyncClient) -> None:
        event = asyncio.Event()
        bp._paused["flow-track"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_MINIMAL_IR,
            curated_ir=_MINIMAL_IR,
            audit=None,
            paused_at_ms=1_700_000_000_000,
            run_id="run-1",
            track_id="agent-1",
            parent_track_id="run-1",
            track_display_name="backend-engineer",
            track_role="subagent",
        )

        response = await client.get("/api/breakpoint/paused/flow-track")

        assert response.status_code == 200
        data = response.json()
        assert data["run_id"] == "run-1"
        assert data["track_id"] == "agent-1"
        assert data["parent_track_id"] == "run-1"
        assert data["track_display_name"] == "backend-engineer"
        assert data["track_role"] == "subagent"

    async def test_returns_tokens_before_when_stamped(
        self, client: AsyncClient
    ) -> None:
        """After the background count lands, GET surfaces the stored value."""
        event = asyncio.Event()
        bp._paused["flow-tok"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_MINIMAL_IR,
            curated_ir=_MINIMAL_IR,
            audit=None,
            paused_at_ms=1_700_000_000_000,
            tokens_before=512,
        )

        response = await client.get("/api/breakpoint/paused/flow-tok")
        assert response.status_code == 200
        assert response.json()["tokens_before"] == 512

    async def test_returns_websocket_transport(self, client: AsyncClient) -> None:
        event = asyncio.Event()
        bp._paused["flow-ws"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_MINIMAL_IR.model_copy(update={"provider": "codex"}),
            curated_ir=_MINIMAL_IR.model_copy(update={"provider": "codex"}),
            transport="websocket",
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )

        response = await client.get("/api/breakpoint/paused/flow-ws")
        assert response.status_code == 200
        assert response.json()["transport"] == "websocket"

    async def test_returns_websocket_provisional_exchange_id(
        self, client: AsyncClient
    ) -> None:
        event = asyncio.Event()
        flow = MagicMock()
        flow.metadata = {
            "manicure_codex_transport": CodexTransportState(
                upgrade=CodexUpgradeMetadata(
                    scheme="wss",
                    host="chatgpt.com",
                    path="/backend-api/codex/responses",
                    request_headers=(),
                    response_status_code=101,
                    response_headers=(),
                ),
                provisional_exchange_id="exchange-provisional-1",
            )
        }
        bp._paused["flow-ws-provisional"] = bp.PausedFlow(
            flow=flow,
            event=event,
            original_ir=_MINIMAL_IR.model_copy(update={"provider": "codex"}),
            curated_ir=_MINIMAL_IR.model_copy(update={"provider": "codex"}),
            transport="websocket",
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )

        response = await client.get("/api/breakpoint/paused/flow-ws-provisional")
        assert response.status_code == 200
        assert response.json()["provisional_exchange_id"] == "exchange-provisional-1"


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

    async def test_re_audit_applies_matching_track_scope(
        self, client: AsyncClient
    ) -> None:
        store = get_store()
        store.upsert(
            Override(kind="system_part_toggle", target="system:0", value=False),
            scope=("run-1", "agent-1"),
        )
        store.upsert(
            Override(kind="system_part_toggle", target="system:0", value=True),
            scope=("run-1", "agent-2"),
        )

        event = asyncio.Event()
        bp._paused["flow-scope"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_IR_WITH_SYSTEM,
            curated_ir=_IR_WITH_SYSTEM,
            audit=None,
            paused_at_ms=1_700_000_000_000,
            run_id="run-1",
            track_id="agent-1",
        )

        response = await client.post("/api/breakpoint/re-audit/flow-scope")

        assert response.status_code == 200
        assert response.json()["curated_ir"]["system"] == []

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

    async def test_re_audit_response_shape_includes_tokens_before(
        self, client: AsyncClient
    ) -> None:
        """tokens_before is part of the contract; null when no counter registered.

        Route tests run without the addon loaded, so ``counting.get_counter()``
        returns None — the field must still be present (as null) so the
        frontend type contract stays stable regardless of addon state.
        """
        event = asyncio.Event()
        bp._paused["flow-shape"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_MINIMAL_IR,
            curated_ir=_MINIMAL_IR,
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )

        response = await client.post("/api/breakpoint/re-audit/flow-shape")
        assert response.status_code == 200
        data = response.json()
        assert "tokens_before" in data
        assert data["tokens_before"] is None

    async def test_re_audit_fires_counter_when_registered(
        self, client: AsyncClient
    ) -> None:
        """When the counter is available, re-audit recounts and persists the result."""
        from manicure import counting

        class _Stub:
            def __init__(self) -> None:
                self.calls = 0

            async def count(
                self, payload: bytes, auth_headers: dict[str, str]
            ) -> int | None:
                self.calls += 1
                return 777

        stub = _Stub()
        counting.set_counter(stub)  # type: ignore[arg-type]
        try:
            event = asyncio.Event()
            pf = bp.PausedFlow(
                flow=None,  # type: ignore[arg-type]
                event=event,
                original_ir=_MINIMAL_IR,
                curated_ir=_MINIMAL_IR,
                audit=None,
                paused_at_ms=1_700_000_000_000,
                auth_headers={"x-api-key": "sk-test"},
            )
            bp._paused["flow-recount"] = pf

            response = await client.post("/api/breakpoint/re-audit/flow-recount")
            assert response.status_code == 200
            data = response.json()
            assert data["tokens_before"] == 777
            assert pf.tokens_before == 777
            assert stub.calls == 1
        finally:
            counting.set_counter(None)

    async def test_re_audit_skips_counter_for_non_anthropic_provider(
        self, client: AsyncClient
    ) -> None:
        from manicure import counting

        class _Stub:
            def __init__(self) -> None:
                self.calls = 0

            async def count(
                self, payload: bytes, auth_headers: dict[str, str]
            ) -> int | None:
                self.calls += 1
                return 1

        stub = _Stub()
        counting.set_counter(stub)  # type: ignore[arg-type]
        try:
            event = asyncio.Event()
            codex_ir = _MINIMAL_IR.model_copy(update={"provider": "codex"})
            bp._paused["flow-codex"] = bp.PausedFlow(
                flow=None,  # type: ignore[arg-type]
                event=event,
                original_ir=codex_ir,
                curated_ir=codex_ir,
                transport="websocket",
                audit=None,
                paused_at_ms=1_700_000_000_000,
                auth_headers={"authorization": "Bearer test"},
            )

            response = await client.post("/api/breakpoint/re-audit/flow-codex")
            assert response.status_code == 200
            assert response.json()["tokens_before"] is None
            assert stub.calls == 0
        finally:
            counting.set_counter(None)

    async def test_re_audit_skips_counter_when_auth_missing(
        self, client: AsyncClient
    ) -> None:
        """Legacy paused flows (no auth_headers stored) must not call the counter."""
        from manicure import counting

        class _Stub:
            def __init__(self) -> None:
                self.calls = 0

            async def count(
                self, payload: bytes, auth_headers: dict[str, str]
            ) -> int | None:
                self.calls += 1
                return 1

        stub = _Stub()
        counting.set_counter(stub)  # type: ignore[arg-type]
        try:
            event = asyncio.Event()
            bp._paused["flow-legacy"] = bp.PausedFlow(
                flow=None,  # type: ignore[arg-type]
                event=event,
                original_ir=_MINIMAL_IR,
                curated_ir=_MINIMAL_IR,
                audit=None,
                paused_at_ms=1_700_000_000_000,
                # auth_headers left as the default empty dict
            )

            response = await client.post("/api/breakpoint/re-audit/flow-legacy")
            assert response.status_code == 200
            assert response.json()["tokens_before"] is None
            assert stub.calls == 0
        finally:
            counting.set_counter(None)


class TestReleaseValidation:
    async def test_release_stashes_validated_payload(self, client: AsyncClient) -> None:
        event = asyncio.Event()
        codex_ir = InternalRequest(
            model="codex/gpt-5-codex",
            provider="codex",
            system=[],
            tools=[],
            messages=[Message(role="user", content=[TextBlock(text="hello")])],
            sampling=SamplingParams(max_tokens=1024),
            metadata=RequestMetadata(),
            stream=False,
            provider_extras={},
        )
        pf = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=codex_ir,
            curated_ir=codex_ir,
            transport="websocket",
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )
        bp._paused["flow-release"] = pf

        response = await client.post(
            "/api/breakpoint/release/flow-release",
            json=codex_ir.model_dump(mode="json"),
        )

        assert response.status_code == 200
        assert pf.event.is_set()
        assert pf.release_payload is not None
        assert json.loads(pf.release_payload.decode())["type"] == "response.create"

    async def test_release_rejects_provider_mismatch(self, client: AsyncClient) -> None:
        event = asyncio.Event()
        pf = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=_MINIMAL_IR,
            curated_ir=_MINIMAL_IR,
            transport="http",
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )
        bp._paused["flow-provider-mismatch"] = pf
        mismatched_ir = _MINIMAL_IR.model_copy(
            update={"provider": "codex", "model": "codex/gpt-5-codex"}
        )

        response = await client.post(
            "/api/breakpoint/release/flow-provider-mismatch",
            json=mismatched_ir.model_dump(mode="json"),
        )

        assert response.status_code == 422
        assert response.json()["detail"] == (
            "Edited request changed provider from anthropic to codex"
        )
        assert not pf.event.is_set()
        assert pf.release_payload is None

    async def test_release_surfaces_serialization_errors(
        self, client: AsyncClient
    ) -> None:
        event = asyncio.Event()
        broken_ir = InternalRequest(
            model="codex/gpt-5-codex",
            provider="codex",
            system=[],
            tools=[],
            messages=[Message(role="user", content=[TextBlock(text="hello")])],
            sampling=SamplingParams(max_tokens=1024),
            metadata=RequestMetadata(),
            stream=False,
            provider_extras={
                "input_item_raw": [
                    {
                        "index": 3,
                        "raw": {
                            "type": "function_call",
                            "call_id": "call_read",
                            "name": "read_file",
                            "arguments": "{}",
                        },
                    }
                ]
            },
        )
        bp._paused["flow-bad-release"] = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=broken_ir,
            curated_ir=broken_ir,
            transport="websocket",
            audit=None,
            paused_at_ms=1_700_000_000_000,
        )

        response = await client.post(
            "/api/breakpoint/release/flow-bad-release",
            json=broken_ir.model_dump(mode="json"),
        )

        assert response.status_code == 422
        assert "Failed to serialize edited request" in response.json()["detail"]
