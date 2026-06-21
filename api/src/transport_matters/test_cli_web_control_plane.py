"""CLI embedded web control-plane regressions."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from httpx import ASGITransport, AsyncClient

from transport_matters import breakpoint as bp
from transport_matters import pause_session
from transport_matters.captured_run import WEB_RUNTIME_EMBEDDED
from transport_matters.flow_state import capture_request_flow_state, get_request_flow_state
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from transport_matters.main import create_app
from transport_matters.run_manager import SpawnRun
from transport_matters.test_run_manager import (
    PreparedRunHarness,
    PtyHarness,
    make_manager,
    patch_pty_teardown,
    resolved_worktree,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


class _Request:
    def __init__(self, body: bytes) -> None:
        self.headers: dict[str, str] = {"content-type": "application/json"}
        self.body = body.decode()

    def set_text(self, text: str) -> None:
        self.body = text


class _Adapter:
    def outbound_request(self, ir: InternalRequest) -> bytes:
        return json.dumps(ir.model_dump(mode="json"), sort_keys=True).encode()


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


def _claude_ir(text: str = "hello") -> InternalRequest:
    return InternalRequest(
        model="anthropic/claude-sonnet-4-20250514",
        provider="anthropic",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text=text)])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
        stream=False,
        provider_extras={},
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


async def test_embedded_run_breakpoint_pause_release_uses_per_run_path_after_cutover(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    prepared = PreparedRunHarness(tmp_path)
    pty = PtyHarness()
    patch_pty_teardown(monkeypatch, pty)
    manager = make_manager(
        tmp_path,
        pty,
        prepared,
        shared_proxy_unavailable_reason="shared proxy unavailable in test",
    )
    managed = await manager.spawn(
        SpawnRun(
            harness="claude",
            resolved_worktree=resolved_worktree(tmp_path),
            web_runtime=WEB_RUNTIME_EMBEDDED,
        )
    )
    assert [request.web_runtime for request in prepared.requests] == [WEB_RUNTIME_EMBEDDED]

    app = create_app()
    transport = ASGITransport(app=app)
    adapter = _Adapter()
    original_ir = _claude_ir()
    released_ir = _claude_ir("released")
    flow = cast(
        "Any",  # Any: SimpleNamespace supplies the HTTPFlow members this path touches.
        SimpleNamespace(
            id="flow-embedded-cutover",
            metadata={},
            request=_Request(adapter.outbound_request(original_ir)),
        ),
    )
    capture_request_flow_state(
        flow,
        adapter=adapter,
        request_ir=original_ir,
        raw_request=adapter.outbound_request(original_ir),
        run_id=managed.run_id,
    )

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            arm = await client.post("/api/breakpoint/arm")
            assert arm.status_code == 200
            assert bp.is_armed() is True

            pause_task = asyncio.create_task(
                pause_session.handle_breakpoint(
                    flow,
                    adapter,
                    original_ir,
                    original_ir,
                    None,
                    None,
                )
            )
            for _ in range(20):
                paused = await client.get("/api/breakpoint/status")
                assert paused.status_code == 200
                if paused.json()["paused_flows"]:
                    break
                await asyncio.sleep(0.01)
            assert [item["flow_id"] for item in paused.json()["paused_flows"]] == [
                "flow-embedded-cutover"
            ]

            released = await client.post(
                "/api/breakpoint/release/flow-embedded-cutover",
                json=released_ir.model_dump(mode="json"),
            )
            assert released.status_code == 200
            await asyncio.wait_for(pause_task, timeout=1.0)
        finally:
            await manager.close()

    request_state = get_request_flow_state(flow)
    assert request_state is not None
    assert request_state.run_id == managed.run_id
    assert request_state.mutated_manually is True
    assert "released" in flow.request.body
    assert flow.request.body != adapter.outbound_request(original_ir).decode()
