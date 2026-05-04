"""Shared helpers for Codex transport tests."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from mitmproxy import http
from mitmproxy.test import tflow

from transport_matters import breakpoint as bp
from transport_matters.overrides import get_store
from transport_matters.storage import init_storage, reset_storage

if TYPE_CHECKING:
    from collections.abc import Generator


def _codex_flow() -> http.HTTPFlow:
    flow = tflow.twebsocketflow(messages=False)
    assert flow.response is not None
    assert flow.websocket is not None
    flow.request.host = "chatgpt.com"
    flow.request.path = "/backend-api/codex/responses?client=cli"
    flow.request.headers["x-codex-session"] = "sess-123"
    flow.response.headers["x-upstream"] = "chatgpt"
    flow.id = "flow-codex-1"
    return flow


def _codex_handshake_failure_flow(
    status_code: int = 403,
    body: bytes = b'{"detail":"Unauthorized websocket upgrade"}',
) -> http.HTTPFlow:
    flow = tflow.tflow()
    flow.request.host = "chatgpt.com"
    flow.request.scheme = "https"
    flow.request.path = "/backend-api/codex/responses?client=cli"
    flow.request.headers["origin"] = "https://chatgpt.com"
    flow.response = http.Response.make(
        status_code,
        body,
        {"content-type": "application/json"},
    )
    flow.id = "flow-codex-handshake"
    return flow


async def _wait_for_pause(flow_id: str) -> None:
    for _ in range(200):
        paused = await bp.get_paused()
        if flow_id in paused:
            return
        await asyncio.sleep(0.001)
    raise AssertionError("flow never paused")


@pytest.fixture(autouse=True)
def _reset_breakpoint_and_overrides() -> None:
    bp.disarm()
    bp._paused.clear()
    store = get_store()
    store.clear()
    store.enabled = True


@pytest.fixture(autouse=True)
def _reset_storage(tmp_path: Any) -> Generator[None]:
    reset_storage()
    init_storage(root=tmp_path)
    yield
    reset_storage()
