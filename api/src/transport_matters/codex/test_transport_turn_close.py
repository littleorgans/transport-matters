"""Codex websocket close and interrupted turn coverage."""

from typing import Any

import pytest
from mitmproxy import websocket
from wsproto.frame_protocol import Opcode

from transport_matters.addon import TransportMattersAddon
from transport_matters.codex.test_transport_support import _codex_flow
from transport_matters.storage import get_storage

pytest_plugins = ("transport_matters.codex.test_transport_support",)
pytestmark = pytest.mark.usefixtures("codex_run_id")


async def test_addon_websocket_end_keeps_turn_artifacts_separated() -> None:
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
            b'{"type":"response.output_text.delta","delta":"hello"}',
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
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"second"}',
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.output_text.delta","delta":"planet"}',
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
    flow.websocket.close_code = 1000
    flow.websocket.close_reason = "done"
    flow.websocket.closed_by_client = False

    await addon.websocket_end(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 2

    by_instruction: dict[str, tuple[Any, Any]] = {}
    for entry in entries:
        artifacts = await storage.read_exchange(entry.id)
        by_instruction[artifacts.request_ir.system[0].text] = (entry, artifacts)

    first_entry, first_artifacts = by_instruction["first"]
    assert first_entry.res is not None
    assert first_entry.res.stop_reason == "completed"
    assert first_entry.res.text_chars == 5
    assert first_artifacts.turn is not None
    assert first_artifacts.turn.turn_index == 0
    assert first_artifacts.transport is not None
    assert [m.event_type for m in first_artifacts.transport.messages] == [
        "response.create",
        "response.output_text.delta",
        "response.completed",
    ]
    assert first_artifacts.transport.close is None

    second_entry, second_artifacts = by_instruction["second"]
    assert second_entry.res is not None
    assert second_entry.res.stop_reason == "completed"
    assert second_entry.res.text_chars == 6
    assert second_artifacts.turn is not None
    assert second_artifacts.turn.turn_index == 1
    assert second_artifacts.transport is not None
    assert [m.event_type for m in second_artifacts.transport.messages] == [
        "response.create",
        "response.output_text.delta",
        "response.completed",
    ]
    assert second_artifacts.transport.close is not None
    assert second_artifacts.transport.close.close_code == 1000


async def test_addon_websocket_end_persists_interrupted_turn_after_prior_finalize() -> None:
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
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"second"}',
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.output_text.delta","delta":"planet"}',
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.close_code = 1006
    flow.websocket.close_reason = "interrupted"
    flow.websocket.closed_by_client = False

    await addon.websocket_end(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 2

    by_instruction: dict[str, tuple[Any, Any]] = {}
    for entry in entries:
        artifacts = await storage.read_exchange(entry.id)
        by_instruction[artifacts.request_ir.system[0].text] = (entry, artifacts)

    first_entry, first_artifacts = by_instruction["first"]
    assert first_entry.res is not None
    assert first_entry.res.stop_reason == "completed"
    assert first_artifacts.transport is not None
    assert first_artifacts.transport.close is None

    second_entry, second_artifacts = by_instruction["second"]
    assert second_entry.res is not None
    assert second_entry.res.stop_reason == "ws_close_1006"
    assert second_artifacts.transport is not None
    assert [m.event_type for m in second_artifacts.transport.messages] == [
        "response.create",
        "response.output_text.delta",
    ]
    assert second_artifacts.transport.close is not None
    assert second_artifacts.transport.close.close_code == 1006
    assert second_artifacts.transport.close.close_reason == "interrupted"
    assert second_artifacts.events is not None
    assert tuple(event.kind for event in second_artifacts.events) == (
        "turn_started",
        "turn_finalized",
    )
    assert second_artifacts.turn is not None
    assert second_artifacts.turn.turn_index == 1
    assert second_artifacts.turn.status == "interrupted"
    assert second_artifacts.turn.stop_reason == "ws_close_1006"
    assert second_artifacts.turn.cursor is None
