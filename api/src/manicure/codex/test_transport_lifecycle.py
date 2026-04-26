"""Addon websocket-end and handshake coverage for Codex transport capture."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, cast
from unittest.mock import patch

import pytest
from mitmproxy import websocket
from wsproto.frame_protocol import Opcode

from manicure import breakpoint as bp
from manicure import broadcast
from manicure.addon import ManicureAddon
from manicure.codex.diagnostics import build_codex_transport_diagnostics
from manicure.codex.test_transport_support import (
    _codex_flow,
    _codex_handshake_failure_flow,
    _wait_for_pause,
)
from manicure.codex.transport import record_codex_websocket_message
from manicure.storage import get_storage

pytest_plugins = ("manicure.codex.test_transport_support",)


async def test_addon_websocket_end_skips_persisting_dropped_codex_exchange() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None
    bp.arm()

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )

    task = asyncio.create_task(addon.websocket_message(flow))
    await _wait_for_pause(flow.id)

    await bp.drop(flow.id)
    await task

    flow.websocket.close_code = 1000
    flow.websocket.close_reason = "dropped"
    flow.websocket.closed_by_client = True
    queue = broadcast.subscribe()
    try:
        await addon.websocket_end(flow)
        storage = await get_storage()
        assert await storage.read_index(limit=10, offset=0) == []
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.01)
    finally:
        broadcast.unsubscribe(queue)


async def test_addon_websocket_end_logs_abnormal_server_close(caplog: Any) -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, b'{"type":"response.create"}')
    )
    await addon.websocket_message(flow)
    flow.websocket.close_code = 1011
    flow.websocket.close_reason = "upstream failure"
    flow.websocket.closed_by_client = False

    with caplog.at_level(logging.WARNING, logger="manicure.addon"):
        await addon.websocket_end(flow)

    assert "CODEX WS END flow-codex-1 close_code=1011 closer=server" in caplog.text


async def test_addon_websocket_end_persists_codex_exchange() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )
    await addon.websocket_message(flow)
    storage = await get_storage()
    provisional = await storage.read_index(limit=10, offset=0)
    assert len(provisional) == 1
    assert provisional[0].res is None
    provisional_id = provisional[0].id
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.output_text.delta","delta":"hello"}',
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.close_code = 1000
    flow.websocket.close_reason = "done"
    flow.websocket.closed_by_client = False

    queue = broadcast.subscribe()
    try:
        await addon.websocket_end(flow)
        event = json.loads(await asyncio.wait_for(queue.get(), timeout=0.01))
        assert event["type"] == "exchange"
        assert event["id"] == provisional_id
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=0.01)
    finally:
        broadcast.unsubscribe(queue)

    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == provisional_id
    assert entry.provider == "codex"
    assert entry.res is not None
    assert entry.res.stop_reason == "completed"
    assert entry.res.text_chars == 5

    artifacts = await storage.read_exchange(entry.id)
    assert artifacts.request_ir.provider == "codex"
    assert artifacts.request_audit is not None
    assert artifacts.transport is not None
    assert artifacts.transport.upgrade.host == "chatgpt.com"
    assert artifacts.transport.close is not None
    assert artifacts.transport.close.close_code == 1000
    assert len(artifacts.transport.messages) >= 3
    assert artifacts.transport.messages[-3].event_type == "response.create"
    assert artifacts.transport.messages[-2].event_type == "response.output_text.delta"
    assert artifacts.transport.messages[-1].event_type == "response.completed"


async def test_addon_websocket_end_survives_default_executor_shutdown() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )
    await addon.websocket_message(flow)
    storage = await get_storage()
    provisional = await storage.read_index(limit=10, offset=0)
    assert len(provisional) == 1
    provisional_id = provisional[0].id

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.output_text.delta","delta":"hello"}',
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.close_code = 1006
    flow.websocket.close_reason = ""
    flow.websocket.closed_by_client = True

    loop = asyncio.get_running_loop()
    original_run_in_executor = loop.run_in_executor

    async def fail_default_executor(
        executor: object,
        func: object,
        *args: object,
    ) -> object:
        if executor is None:
            raise RuntimeError("Executor shutdown has been called")
        return await original_run_in_executor(
            cast("Any", executor),
            cast("Any", func),
            *args,
        )

    with patch.object(loop, "run_in_executor", side_effect=fail_default_executor):
        await addon.websocket_end(flow)

    entry = await storage.read_index_entry(provisional_id)
    assert entry is not None
    assert entry.res is not None
    assert entry.res.stop_reason == "completed"

    artifacts = await storage.read_exchange(provisional_id)
    assert artifacts.transport is not None
    assert artifacts.transport.close is not None
    assert artifacts.transport.close.close_code == 1006
    assert artifacts.transport.close.closed_by_client is True
    assert artifacts.transport.messages[-2].event_type == "response.output_text.delta"
    assert artifacts.transport.messages[-1].event_type == "response.completed"


async def test_addon_websocket_end_cancellation_restores_provisional_exchange() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )
    await addon.websocket_message(flow)
    storage = await get_storage()
    provisional = await storage.read_index(limit=10, offset=0)
    assert len(provisional) == 1
    provisional_id = provisional[0].id

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.close_code = 1000
    flow.websocket.close_reason = "done"
    flow.websocket.closed_by_client = False

    async def cancel_rewrite(_: dict[str, object]) -> None:
        raise asyncio.CancelledError()

    with (
        patch.object(storage, "_rewrite_index", side_effect=cancel_rewrite),
        pytest.raises(asyncio.CancelledError),
    ):
        await addon.websocket_end(flow)

    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    assert entries[0].id == provisional_id
    assert entries[0].res is None

    artifacts = await storage.read_exchange(provisional_id)
    assert artifacts.transport is not None
    assert artifacts.transport.close is None
    assert artifacts.transport.messages[-1].event_type == "response.create"


async def test_addon_websocket_end_tolerates_nested_non_string_type_fields() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"original"}',
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            (
                b'{"type":"response.output_item.added","item":{"type":{"kind":"tool"},"id":"item-1"}}'
            ),
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
        )
    )
    record_codex_websocket_message(flow)
    flow.websocket.close_code = 1000
    flow.websocket.close_reason = "done"
    flow.websocket.closed_by_client = False

    await addon.websocket_end(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.provider == "codex"
    assert entry.res is not None
    assert entry.res.stop_reason == "completed"
    assert entry.res.tool_calls == 0


async def test_addon_response_persists_codex_handshake_failure() -> None:
    addon = ManicureAddon()
    flow = _codex_handshake_failure_flow()

    await addon.response(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.provider == "codex"
    assert entry.model == "codex/transport-handshake"
    assert entry.res is not None
    assert entry.res.stop_reason == "websocket_handshake_failed"

    artifacts = await storage.read_exchange(entry.id)
    assert artifacts.response_raw is not None
    assert b"Unauthorized websocket upgrade" in artifacts.response_raw
    assert artifacts.transport is not None
    assert artifacts.transport.upgrade.response_status_code == 403
    assert artifacts.transport.messages == []


async def test_addon_response_preserves_raw_handshake_failure_bytes() -> None:
    addon = ManicureAddon()
    raw_body = (
        b"TLS error: invalid peer certificate: UnknownIssuer\xff"
        b"\xfe while upgrading websocket"
    )
    flow = _codex_handshake_failure_flow(status_code=502, body=raw_body)

    await addon.response(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1

    artifacts = await storage.read_exchange(entries[0].id)
    assert artifacts.response_raw == raw_body
    diagnostics = build_codex_transport_diagnostics(artifacts)
    assert diagnostics[0].code == "proxy_trust_failed"
    assert "response body redacted" in (diagnostics[0].detail or "")
    assert "UnknownIssuer" not in (diagnostics[0].detail or "")
