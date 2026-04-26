"""Focused multi turn tests for Codex websocket transport capture."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

from mitmproxy import websocket
from wsproto.frame_protocol import Opcode

from manicure import breakpoint as bp
from manicure.addon import ManicureAddon
from manicure.codex.transport import ensure_codex_transport_state
from manicure.flow_state import get_request_flow_state
from manicure.storage import get_storage

from .test_transport_support import (
    _codex_flow,
    _wait_for_pause,
)

if TYPE_CHECKING:
    import pytest

pytest_plugins = ("manicure.codex.test_transport_support",)


async def test_addon_websocket_message_finalizes_turn_on_server_completion() -> None:
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

    state = ensure_codex_transport_state(flow)
    assert state is not None
    assert state.provisional_exchange_id is None

    finalized_entry = entries[0]
    assert finalized_entry.res is not None
    assert finalized_entry.res.stop_reason == "completed"
    assert finalized_entry.res.text_chars == 5
    assert finalized_entry.codex_turn is not None
    assert finalized_entry.codex_turn.status == "completed"
    assert finalized_entry.codex_turn.message_range_start == 0
    assert finalized_entry.codex_turn.message_range_end == 2

    finalized_artifacts = await storage.read_exchange(finalized_entry.id)
    assert finalized_artifacts.response_ir is not None
    assert finalized_artifacts.response_ir.provider == "codex"
    assert finalized_artifacts.response_ir.stop_reason == "completed"
    assert finalized_artifacts.response_ir.content[0].type == "text"
    assert finalized_artifacts.response_ir.content[0].text == "hello"
    assert finalized_artifacts.transport is not None
    assert [m.event_type for m in finalized_artifacts.transport.messages] == [
        "response.create",
        "response.output_text.delta",
        "response.completed",
    ]
    assert finalized_artifacts.transport.close is None
    assert finalized_artifacts.events is not None
    assert tuple(event.kind for event in finalized_artifacts.events) == (
        "turn_started",
        "response_completed",
        "turn_finalized",
    )
    assert finalized_artifacts.turn is not None
    assert finalized_artifacts.turn.turn_index == 0
    assert finalized_artifacts.turn.status == "completed"
    assert finalized_artifacts.turn.terminal_message_index == 2
    assert finalized_artifacts.turn.text_chars == len("hello")
    assert finalized_artifacts.turn.cursor is None

    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            True,
            b'{"type":"response.create","model":"gpt-5-codex","instructions":"second"}',
        )
    )
    await addon.websocket_message(flow)

    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 2

    state = ensure_codex_transport_state(flow)
    assert state is not None
    assert state.provisional_exchange_id is not None

    provisional_entry = next(
        entry for entry in entries if entry.id == state.provisional_exchange_id
    )
    rotated_entry = next(
        entry for entry in entries if entry.id != state.provisional_exchange_id
    )
    assert provisional_entry.res is None
    assert provisional_entry.codex_turn is not None
    assert provisional_entry.codex_turn.status == "open"
    assert provisional_entry.codex_turn.message_range_start == 0
    assert provisional_entry.codex_turn.message_range_end == 0
    assert rotated_entry.id == finalized_entry.id
    assert rotated_entry.res is not None
    assert rotated_entry.res.stop_reason == "completed"

    provisional_artifacts = await storage.read_exchange(provisional_entry.id)
    assert provisional_artifacts.transport is not None
    assert [m.event_type for m in provisional_artifacts.transport.messages] == [
        "response.create"
    ]
    assert provisional_artifacts.transport.close is None


async def test_addon_websocket_message_finalizes_turn_from_output_items() -> None:
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
            (
                b'{"type":"response.output_item.done","item":{"id":"msg_01","type":"message","status":"completed","phase":"final_answer","role":"assistant","content":[{"type":"output_text","text":"assistant text"}]}}'
            ),
        )
    )
    await addon.websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(
            Opcode.TEXT,
            False,
            (
                b'{"type":"response.completed","response":{"id":"resp_01","model":"gpt-5-codex","status":"completed","usage":{"input_tokens":12,"input_tokens_details":{"cached_tokens":5},"output_tokens":7}}}'
            ),
        )
    )
    await addon.websocket_message(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.res is not None
    assert entry.res.stop_reason == "completed"
    assert entry.res.input_tokens == 12
    assert entry.res.cache_read_input_tokens == 5
    assert entry.res.output_tokens == 7
    assert entry.res.text_chars == len("assistant text")

    artifacts = await storage.read_exchange(entry.id)
    assert artifacts.response_ir is not None
    assert artifacts.response_ir.id == "resp_01"
    assert artifacts.response_ir.model == "codex/gpt-5-codex"
    assert artifacts.response_ir.content[0].type == "text"
    assert artifacts.response_ir.content[0].text == "assistant text"
    assert artifacts.response_ir.provider_extras["output_item_meta"][0]["phase"] == (
        "final_answer"
    )


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


async def test_addon_websocket_message_finalizes_failed_turn() -> None:
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
            b'{"type":"response.failed","response":{"status":"failed"}}',
        )
    )
    await addon.websocket_message(flow)

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    assert len(entries) == 1

    state = ensure_codex_transport_state(flow)
    assert state is not None
    assert state.provisional_exchange_id is None

    entry = entries[0]
    assert entry.res is not None
    assert entry.res.stop_reason == "failed"

    artifacts = await storage.read_exchange(entry.id)
    assert artifacts.transport is not None
    assert [m.event_type for m in artifacts.transport.messages] == [
        "response.create",
        "response.failed",
    ]
    assert artifacts.transport.close is None
    assert artifacts.events is not None
    assert tuple(event.kind for event in artifacts.events) == (
        "turn_started",
        "response_failed",
        "turn_finalized",
    )
    assert artifacts.turn is not None
    assert artifacts.turn.status == "failed"
    assert artifacts.turn.cursor is None


async def test_addon_websocket_end_keeps_turn_artifacts_separated() -> None:
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


async def test_addon_websocket_end_persists_interrupted_turn_after_prior_finalize() -> (
    None
):
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


async def test_addon_websocket_message_can_pause_second_response_create_turn() -> None:
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


async def test_addon_websocket_message_clears_stale_request_state() -> None:
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
