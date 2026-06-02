"""Unit tests for Codex websocket transport helpers."""

from __future__ import annotations

import json

from mitmproxy import websocket
from wsproto.frame_protocol import Opcode

from transport_matters.codex.response_parser import parse_codex_response_payloads
from transport_matters.codex.test_transport_support import _codex_flow
from transport_matters.codex.transport import (
    build_codex_transport_artifacts,
    close_codex_transport,
    ensure_codex_transport_state,
    is_codex_websocket_flow,
    record_codex_websocket_message,
)

pytest_plugins = ("transport_matters.codex.test_transport_support",)


def test_is_codex_websocket_flow_only_matches_target_path() -> None:
    flow = _codex_flow()
    assert is_codex_websocket_flow(flow) is True

    flow.request.path = "/backend-api/plugins/featured"
    assert is_codex_websocket_flow(flow) is False

    flow.request.host = "chatgpt.com"
    flow.request.path = "/backend-api/codex/responses-extra"
    assert is_codex_websocket_flow(flow) is False

    flow.request.host = "api.openai.com"
    flow.request.path = "/backend-api/codex/responses"
    assert is_codex_websocket_flow(flow) is False


def test_ensure_codex_transport_state_captures_upgrade_metadata() -> None:
    flow = _codex_flow()

    state = ensure_codex_transport_state(flow)

    assert state is not None
    assert state.upgrade.host == "chatgpt.com"
    assert state.upgrade.path == "/backend-api/codex/responses?client=cli"
    assert state.upgrade.response_status_code == 101
    assert ("session-id", "sess-123") in state.upgrade.request_headers
    assert ("thread-id", "thread-123") in state.upgrade.request_headers
    assert ("x-upstream", "chatgpt") in state.upgrade.response_headers


def test_record_codex_websocket_message_tracks_counts_and_initial_frame() -> None:
    flow = _codex_flow()
    state = ensure_codex_transport_state(flow)
    assert state is not None
    assert flow.websocket is not None

    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, False, b'{"type":"response.output_text.delta"}')
    )
    update = record_codex_websocket_message(flow)
    assert update is not None
    state, _, captured_initial = update
    assert captured_initial is False
    assert state.server_message_count == 1
    assert state.initial_client_frame is None

    first_client_frame = b'{"type":"response.create","instructions":"hi"}'
    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, first_client_frame)
    )
    update = record_codex_websocket_message(flow)
    assert update is not None
    state, _, captured_initial = update
    assert captured_initial is True
    assert state.client_message_count == 1
    assert state.initial_client_frame == first_client_frame
    assert state.initial_client_frame_text == first_client_frame.decode()
    assert state.initial_client_frame_is_text is True

    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, b'{"type":"response.cancel"}')
    )
    update = record_codex_websocket_message(flow)
    assert update is not None
    state, _, captured_initial = update
    assert captured_initial is False
    assert state.client_message_count == 2
    assert state.initial_client_frame == first_client_frame

    second_client_frame = b'{"type":"response.create","instructions":"second"}'
    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, second_client_frame)
    )
    update = record_codex_websocket_message(flow)
    assert update is not None
    state, _, captured_initial = update
    assert captured_initial is True
    assert state.client_message_count == 3
    assert state.initial_client_frame == second_client_frame
    assert state.initial_client_frame_text == second_client_frame.decode()


def test_record_codex_websocket_message_allocates_continuity_from_headers() -> None:
    flow = _codex_flow()
    flow.request.headers["session-id"] = "session-real"
    flow.request.headers["thread-id"] = "thread-real"
    flow.request.headers["x-codex-turn-metadata"] = json.dumps({"turn_id": "turn-real"})
    assert flow.websocket is not None
    ensure_codex_transport_state(flow)

    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, b'{"type":"response.create"}')
    )
    update = record_codex_websocket_message(flow)

    assert update is not None
    state, _, captured_initial = update
    assert captured_initial is True
    assert state.current_turn_allocation is not None
    assert state.current_turn_allocation.session_id == "session-real"
    assert state.current_turn_allocation.thread_id == "thread-real"
    assert state.current_turn_allocation.turn_id == "turn-real"
    assert state.current_turn_allocation.turn_index == 0
    assert state.current_turn_allocation.continuity == "exact"

    retry_flow = _codex_flow()
    retry_flow.request.headers["session-id"] = "session-real"
    retry_flow.request.headers["thread-id"] = "thread-real"
    retry_flow.request.headers["x-codex-turn-metadata"] = json.dumps({"turn_id": "turn-real"})
    assert retry_flow.websocket is not None
    ensure_codex_transport_state(retry_flow)
    retry_flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, b'{"type":"response.create"}')
    )

    retry_update = record_codex_websocket_message(retry_flow)

    assert retry_update is not None
    retry_state, _, _ = retry_update
    assert retry_state.current_turn_allocation is not None
    assert retry_state.current_turn_allocation.turn_index == 0


def test_record_codex_websocket_message_advances_lossy_turns() -> None:
    flow = _codex_flow()
    assert flow.websocket is not None
    ensure_codex_transport_state(flow)

    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, b'{"type":"response.create"}')
    )
    first_update = record_codex_websocket_message(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, b'{"type":"response.create"}')
    )
    second_update = record_codex_websocket_message(flow)

    assert first_update is not None
    assert second_update is not None
    state, _, _ = second_update
    assert state.current_turn_allocation is not None
    assert state.current_turn_allocation.turn_id is None
    assert state.current_turn_allocation.turn_index == 1
    assert state.current_turn_allocation.continuity == "lossy"


def test_close_codex_transport_reports_close_state() -> None:
    flow = _codex_flow()
    ensure_codex_transport_state(flow)
    assert flow.websocket is not None
    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, b'{"type":"response.create"}')
    )
    record_codex_websocket_message(flow)
    flow.websocket.close_code = 1011
    flow.websocket.close_reason = "upstream reset"
    flow.websocket.closed_by_client = False

    summary = close_codex_transport(flow)

    assert summary is not None
    assert summary.close_code == 1011
    assert summary.close_reason == "upstream reset"
    assert summary.closed_by_client is False
    assert summary.initial_client_frame_captured is True
    assert summary.is_normal is False


def test_build_codex_transport_artifacts_redacts_sensitive_upgrade_headers() -> None:
    flow = _codex_flow()
    flow.request.headers["authorization"] = "Bearer super-secret"
    flow.request.headers["cookie"] = "oai-session=secret"
    assert flow.response is not None
    flow.response.headers["set-cookie"] = "session=secret; Path=/"

    ensure_codex_transport_state(flow)
    transport = build_codex_transport_artifacts(flow)

    assert transport is not None
    request_headers = {header.name: header.value for header in transport.upgrade.request_headers}
    response_headers = {header.name: header.value for header in transport.upgrade.response_headers}
    assert request_headers["authorization"] == "Bearer [redacted]"
    assert request_headers["cookie"] == "[redacted]"
    assert request_headers["session-id"] == "sess-123"
    assert request_headers["thread-id"] == "thread-123"
    assert response_headers["set-cookie"] == "[redacted]"
    assert response_headers["x-upstream"] == "chatgpt"


def test_parse_codex_response_payloads_prefers_completed_output_items_and_usage() -> None:
    response = parse_codex_response_payloads(
        [
            {
                "type": "response.output_item.done",
                "item": {
                    "id": "rs_01",
                    "type": "reasoning",
                    "status": "completed",
                    "encrypted_content": "opaque",
                    "summary": [{"type": "summary_text", "text": "considering tradeoffs"}],
                },
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "id": "fc_01",
                    "call_id": "call_01",
                    "type": "function_call",
                    "status": "completed",
                    "name": "exec_command",
                    "arguments": '{"cmd":"pwd"}',
                },
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "id": "msg_01",
                    "type": "message",
                    "status": "completed",
                    "phase": "final_answer",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": "assistant text"},
                    ],
                },
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "id": "tsc_01",
                    "call_id": "call_search",
                    "type": "tool_search_call",
                    "status": "completed",
                    "arguments": {
                        "query": "fmm structural code navigation",
                        "limit": 12,
                    },
                    "execution": "client",
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_01",
                    "model": "gpt-5-codex",
                    "status": "completed",
                    "usage": {
                        "input_tokens": 12,
                        "input_tokens_details": {"cached_tokens": 5},
                        "output_tokens": 7,
                    },
                },
            },
        ]
    )

    assert response is not None
    assert response.id == "resp_01"
    assert response.model == "codex/gpt-5-codex"
    assert response.stop_reason == "completed"
    assert response.usage.input_tokens == 12
    assert response.usage.cache_read_input_tokens == 5
    assert response.usage.output_tokens == 7
    assert response.content[0].type == "thinking"
    assert response.content[1].type == "tool_use"
    assert response.content[2].type == "text"
    assert response.content[2].text == "assistant text"
    assert response.content[3].type == "tool_use"
    assert response.content[3].name == "tool_search"
    assert response.content[3].id == "call_search"
    assert response.content[3].input == {
        "query": "fmm structural code navigation",
        "limit": 12,
    }
    assert response.provider_extras["output_item_meta"][2]["phase"] == "final_answer"
    assert response.provider_extras["output_item_meta"][3]["type"] == "tool_search_call"
