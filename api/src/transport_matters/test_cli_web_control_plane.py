"""CLI embedded web control-plane regressions."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from transport_matters import breakpoint as bp
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from transport_matters.main import create_app

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def _reset_breakpoint() -> Generator[None]:
    bp.disarm()
    bp._paused.clear()
    yield
    bp.disarm()
    bp._paused.clear()


def _codex_ir() -> InternalRequest:
    return InternalRequest(
        model="codex/gpt-5-codex",
        provider="codex",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hello")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
        stream=False,
        provider_extras={"type": "response.create"},
    )


async def test_cli_embedded_web_arm_pause_release_shares_addon_state() -> None:
    app = create_app()
    transport = ASGITransport(app=app)
    ir = _codex_ir()
    flow = SimpleNamespace(id="flow-cli")

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        arm = await client.post("/api/breakpoint/arm")
        assert arm.status_code == 200
        assert bp.is_armed() is True

        release_event = await bp.pause(flow, ir, ir, transport="websocket", run_id="run-cli")  # type: ignore[arg-type]
        paused = await client.get("/api/breakpoint/status")
        assert paused.status_code == 200
        assert [item["flow_id"] for item in paused.json()["paused_flows"]] == ["flow-cli"]

        released = await client.post(
            "/api/breakpoint/release/flow-cli",
            json=ir.model_dump(mode="json"),
        )
        assert released.status_code == 200
        assert release_event.is_set()

    await asyncio.wait_for(release_event.wait(), timeout=1.0)
    assert (await bp.get_paused())["flow-cli"].release_payload is not None
