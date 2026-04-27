"""Codex websocket derived artifact and tool result coverage."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING
from unittest.mock import patch

from mitmproxy import websocket
from wsproto.frame_protocol import Opcode

from manicure.addon import ManicureAddon
from manicure.codex.test_transport_support import _codex_flow
from manicure.codex.transport import ensure_codex_transport_state
from manicure.storage import get_storage

pytest_plugins = ("manicure.codex.test_transport_support",)

if TYPE_CHECKING:
    import pytest


async def test_addon_websocket_message_preserves_open_sidecars_when_derivation_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    addon = ManicureAddon()
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

    storage = await get_storage()
    provisional_entries = await storage.read_index(limit=10, offset=0)
    assert len(provisional_entries) == 1
    provisional_entry = provisional_entries[0]
    assert provisional_entry.codex_turn is not None
    assert provisional_entry.codex_turn.status == "open"

    provisional_artifacts = await storage.read_exchange(provisional_entry.id)
    assert provisional_artifacts.events is not None
    assert provisional_artifacts.turn is not None
    assert provisional_artifacts.turn.status == "open"

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            b'{"type":"response.completed","response":{"status":"completed"}}',
        )
    )
    with (
        caplog.at_level(logging.WARNING, logger="manicure.codex.exchange"),
        patch(
            "manicure.codex.exchange._advance_codex_derived_artifacts",
            return_value=None,
        ),
        patch(
            "manicure.codex.exchange._replay_codex_derived_artifacts",
            return_value=None,
        ),
    ):
        await addon.websocket_message(flow)

    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.id == provisional_entry.id
    assert entry.res is not None
    assert entry.res.stop_reason == "completed"
    assert entry.res.text_chars == len("hello")
    assert entry.codex_turn == provisional_entry.codex_turn
    assert "Final Codex derivation failed for exchange" in caplog.text
    assert "preserving prior derived artifacts" in caplog.text

    state = ensure_codex_transport_state(flow)
    assert state is not None
    assert state.provisional_exchange_id is None

    artifacts = await storage.read_exchange(entry.id)
    assert artifacts.response_ir is not None
    assert artifacts.response_ir.stop_reason == "completed"
    assert artifacts.response_ir.content[0].type == "text"
    assert artifacts.response_ir.content[0].text == "hello"
    assert artifacts.events == provisional_artifacts.events
    assert artifacts.turn == provisional_artifacts.turn
    assert artifacts.transport is not None
    assert [message.event_type for message in artifacts.transport.messages] == [
        "response.create",
        "response.output_text.delta",
        "response.completed",
    ]


async def test_addon_websocket_message_derives_tool_result_only_turn() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            (
                b'{"type":"response.create","model":"gpt-5-codex","instructions":"continue","input":[{"type":"function_call_output","call_id":"call_prev","output":"README contents"}]}'
            ),
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

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1

    artifacts = await storage.read_exchange(entries[0].id)
    assert artifacts.events is not None
    assert tuple(event.kind for event in artifacts.events) == (
        "turn_started",
        "tool_output_submitted",
        "response_completed",
        "turn_finalized",
    )
    assert artifacts.events[1].data == {
        "call_id": "call_prev",
        "input_index": 0,
        "item_type": "function_call_output",
        "output_chars": len("README contents"),
    }
    assert artifacts.turn is not None
    assert artifacts.turn.status == "completed"
    assert artifacts.turn.text_chars == 0
    assert artifacts.turn.tool_calls == 0


async def test_addon_websocket_message_persists_tool_search_output_turn() -> None:
    addon = ManicureAddon()
    flow = _codex_flow()
    assert flow.websocket is not None

    addon.websocket_start(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            (
                b'{"type":"response.create","model":"gpt-5-codex",'
                b'"instructions":"first"}'
            ),
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            (
                b'{"type":"response.output_item.done","item":{'
                b'"id":"tsc_01","type":"tool_search_call",'
                b'"status":"completed","call_id":"call_search",'
                b'"arguments":{"query":"fmm","limit":12},'
                b'"execution":"client"}}'
            ),
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

    continuation = {
        "type": "response.create",
        "model": "gpt-5-codex",
        "input": [
            {
                "type": "tool_search_output",
                "call_id": "call_search",
                "status": "completed",
                "execution": "client",
                "tools": [
                    {
                        "type": "namespace",
                        "name": "mcp__fmm__",
                        "description": "Tools in the mcp__fmm__ namespace.",
                        "tools": [
                            {
                                "type": "function",
                                "name": "fmm_list_files",
                                "description": "List indexed files.",
                                "parameters": {"type": "object", "properties": {}},
                            }
                        ],
                    }
                ],
            }
        ],
        "tools": [],
    }
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            json.dumps(continuation, separators=(",", ":")).encode(),
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            (
                b'{"type":"response.output_item.done","item":{'
                b'"id":"msg_01","type":"message","status":"completed",'
                b'"role":"assistant","content":[{"type":"output_text",'
                b'"text":"fmm is available"}]}}'
            ),
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

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 2
    all_artifacts = [await storage.read_exchange(entry.id) for entry in entries]
    artifacts = next(
        artifact
        for artifact in all_artifacts
        if artifact.request_ir.messages
        and artifact.request_ir.messages[0].content
        and artifact.request_ir.messages[0].content[0].type == "tool_result"
    )
    assert artifacts.request_ir.messages[0].content[0].type == "tool_result"
    assert "input_item_raw" not in artifacts.request_ir.provider_extras
    assert artifacts.response_ir is not None
    assert artifacts.response_ir.content[0].type == "text"
    assert artifacts.response_ir.content[0].text == "fmm is available"
