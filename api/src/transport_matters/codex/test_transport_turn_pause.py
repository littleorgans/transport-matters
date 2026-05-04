"""Codex websocket pause and stale request state coverage."""

from __future__ import annotations

import asyncio
import json

from mitmproxy import websocket
from wsproto.frame_protocol import Opcode

from transport_matters import breakpoint as bp
from transport_matters.addon import TransportMattersAddon
from transport_matters.codex.test_transport_support import _codex_flow, _wait_for_pause
from transport_matters.codex.transport import ensure_codex_transport_state
from transport_matters.flow_state import get_request_flow_state
from transport_matters.storage import get_storage

pytest_plugins = ("transport_matters.codex.test_transport_support",)


async def test_addon_websocket_message_can_pause_second_response_create_turn() -> None:
    addon = TransportMattersAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"first"}',
        )
    )
    await addon.websocket_message(flow)

    bp.arm()
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"second"}',
        )
    )

    task = asyncio.create_task(addon.websocket_message(flow))
    await _wait_for_pause(flow.id)

    paused = await bp.get_paused()
    pf = paused[flow.id]
    assert pf.curated_ir.system[0].text == "second"

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 2

    state = ensure_codex_transport_state(flow)
    assert state is not None
    assert state.provisional_exchange_id is not None
    provisional = await storage.read_exchange(state.provisional_exchange_id)
    assert provisional.request_ir.system[0].text == "second"

    edited_ir = pf.curated_ir.model_copy(
        update={
            "system": [
                part.model_copy(update={"text": "second edited"})
                for part in pf.curated_ir.system
            ]
        }
    )
    await bp.release(
        flow.id,
        edited_ir,
        (
            b'{"type":"response.create","model":"gpt-5-codex",'
            b'"instructions":"second edited","input":[],"tools":[]}'
        ),
    )
    await task

    payload = json.loads(flow.websocket.messages[-1].content.decode())
    assert payload["instructions"] == "second edited"


async def test_addon_websocket_message_clears_stale_request_state() -> None:
    addon = TransportMattersAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"first"}',
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
        )
    )
    await addon.websocket_message(flow)

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","instructions":"missing model"}',
        )
    )
    await addon.websocket_message(flow)

    assert get_request_flow_state(flow) is None

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.close_code = 1000
    flow.websocket.close_reason = "done"
    flow.websocket.closed_by_client = False

    await addon.websocket_end(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1

    entry = entries[0]
    artifacts = await storage.read_exchange(entry.id)
    assert entry.res is not None
    assert artifacts.request_ir.system[0].text == "first"
    assert artifacts.transport is not None
    assert [message.event_type for message in artifacts.transport.messages] == [
        "response.create",
        "response.completed",
    ]
