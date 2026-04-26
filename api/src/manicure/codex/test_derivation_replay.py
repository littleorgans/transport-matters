from __future__ import annotations

from manicure.codex.derivation import (
    CodexDerivationOperatorFact,
    CodexReplayRequest,
    derive_codex_turn_replay,
)

from .test_derivation_support import (
    make_close,
    make_context,
    make_message,
    ts,
)


def _completed_replay_request() -> CodexReplayRequest:
    return CodexReplayRequest(
        context=make_context(),
        operator_facts=[
            CodexDerivationOperatorFact(
                kind="request_curated",
                ts=ts(10, 14, 2),
            ),
            CodexDerivationOperatorFact(
                kind="breakpoint_paused",
                ts=ts(10, 14, 2),
            ),
            CodexDerivationOperatorFact(
                kind="breakpoint_released",
                ts=ts(10, 14, 2),
            ),
        ],
        transport_messages=[
            make_message(
                23,
                10,
                14,
                3,
                direction="client",
                event_type="response.create",
                payload_json={
                    "type": "response.create",
                    "model": "gpt-5-codex",
                    "input": [
                        {
                            "type": "function_call_output",
                            "call_id": "call_prev",
                            "output": "README contents",
                        }
                    ],
                },
            ),
            make_message(
                24,
                10,
                14,
                4,
                direction="server",
                event_type="response.output_item.added",
                payload_json={
                    "type": "response.output_item.added",
                    "item": {
                        "type": "function_call",
                        "id": "fc_01",
                        "call_id": "call_read",
                        "name": "read_file",
                        "arguments": "",
                    },
                },
            ),
            make_message(
                25,
                10,
                14,
                5,
                direction="server",
                event_type="response.function_call_arguments.delta",
                payload_json={
                    "type": "response.function_call_arguments.delta",
                    "item_id": "fc_01",
                    "call_id": "call_read",
                    "delta": '{"path":"README',
                },
            ),
            make_message(
                26,
                10,
                14,
                6,
                direction="server",
                event_type="response.function_call_arguments.done",
                payload_json={
                    "type": "response.function_call_arguments.done",
                    "item_id": "fc_01",
                    "call_id": "call_read",
                    "arguments": '{"path":"README.md"}',
                },
            ),
            make_message(
                27,
                10,
                14,
                7,
                direction="server",
                event_type="response.output_item.done",
                payload_json={
                    "type": "response.output_item.done",
                    "item": {
                        "type": "function_call",
                        "id": "fc_01",
                        "call_id": "call_read",
                        "name": "read_file",
                        "arguments": '{"path":"README.md"}',
                    },
                },
            ),
            make_message(
                28,
                10,
                14,
                8,
                direction="server",
                event_type="response.output_text.delta",
                payload_json={
                    "type": "response.output_text.delta",
                    "item_id": "msg_01",
                    "delta": "hello",
                },
            ),
            make_message(
                29,
                10,
                14,
                9,
                direction="server",
                event_type="response.output_item.done",
                payload_json={
                    "type": "response.output_item.done",
                    "item": {
                        "id": "msg_01",
                        "type": "message",
                        "status": "completed",
                        "phase": "final_answer",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "hello",
                            }
                        ],
                    },
                },
            ),
            make_message(
                30,
                10,
                14,
                10,
                direction="server",
                event_type="response.completed",
                payload_json={
                    "type": "response.completed",
                    "response": {
                        "id": "resp_01",
                        "status": "completed",
                    },
                },
            ),
        ],
    )


def test_replay_derives_completed_turn_with_committed_semantics_only() -> None:
    result = derive_codex_turn_replay(_completed_replay_request())

    assert result is not None
    assert tuple(event.kind for event in result.events) == (
        "turn_started",
        "request_curated",
        "breakpoint_paused",
        "breakpoint_released",
        "tool_output_submitted",
        "tool_call_completed",
        "assistant_item_completed",
        "response_completed",
        "turn_finalized",
    )
    assert tuple(event.source for event in result.events) == (
        "client",
        "proxy",
        "operator",
        "operator",
        "client",
        "server",
        "server",
        "server",
        "proxy",
    )
    assert tuple(
        event.transport_ref.message_index if event.transport_ref is not None else None
        for event in result.events
    ) == (23, None, None, None, 23, 27, 29, 30, None)
    assert result.events[4].data == {
        "call_id": "call_prev",
        "input_index": 0,
        "item_type": "function_call_output",
        "output_chars": len("README contents"),
    }
    assert result.events[5].data == {
        "arguments_chars": len('{"path":"README.md"}'),
        "call_id": "call_read",
        "item_id": "fc_01",
        "item_type": "function_call",
        "tool_name": "read_file",
    }
    assert result.events[6].data == {
        "item_id": "msg_01",
        "item_type": "message",
        "phase": "final_answer",
        "role": "assistant",
        "text_chars": 5,
    }
    assert result.events[7].data == {
        "response_id": "resp_01",
        "response_status": "completed",
        "stop_reason": "completed",
    }
    assert result.events[8].data == {
        "status": "completed",
        "stop_reason": "completed",
        "terminal_cause": "response_completed",
        "text_chars": 5,
        "tool_calls": 1,
    }
    assert result.turn.status == "completed"
    assert result.turn.terminal_message_index == 30
    assert result.turn.terminal_cause == "response_completed"
    assert result.turn.message_range_end == 30
    assert result.turn.text_chars == 5
    assert result.turn.tool_calls == 1
    assert result.turn.cursor is None


def test_replay_derives_interrupted_turn_from_close_fact() -> None:
    result = derive_codex_turn_replay(
        CodexReplayRequest(
            context=make_context(),
            transport_messages=[
                make_message(
                    23,
                    10,
                    14,
                    3,
                    direction="client",
                    event_type="response.create",
                    payload_json={
                        "type": "response.create",
                        "model": "gpt-5-codex",
                    },
                ),
                make_message(
                    24,
                    10,
                    14,
                    4,
                    direction="server",
                    event_type="response.output_text.delta",
                    payload_json={
                        "type": "response.output_text.delta",
                        "item_id": "msg_01",
                        "delta": "hello",
                    },
                ),
            ],
            close=make_close(10, 14, 5, close_code=1006),
        )
    )

    assert result is not None
    assert tuple(event.kind for event in result.events) == (
        "turn_started",
        "turn_finalized",
    )
    assert result.events[-1].data == {
        "close_code": 1006,
        "status": "interrupted",
        "stop_reason": "ws_close_1006",
        "terminal_cause": "websocket_close",
        "text_chars": 5,
        "tool_calls": 0,
    }
    assert result.turn.status == "interrupted"
    assert result.turn.terminal_cause == "websocket_close"
    assert result.turn.terminal_message_index is None
    assert result.turn.stop_reason == "ws_close_1006"
    assert result.turn.text_chars == 5
    assert result.turn.message_range_end == 24


def test_replay_returns_none_for_dropped_or_missing_turn_start() -> None:
    dropped = derive_codex_turn_replay(
        CodexReplayRequest(
            context=make_context(),
            transport_messages=[
                make_message(
                    23,
                    10,
                    14,
                    3,
                    direction="client",
                    event_type="response.create",
                    dropped=True,
                ),
            ],
            close=make_close(10, 14, 4),
        )
    )
    handshake_failure = derive_codex_turn_replay(
        CodexReplayRequest(
            context=make_context(),
            transport_messages=[
                make_message(
                    23,
                    10,
                    14,
                    3,
                    direction="server",
                    event_type="response.failed",
                    payload_json={
                        "type": "response.failed",
                        "response": {"status": "failed"},
                    },
                )
            ],
        )
    )

    assert dropped is None
    assert handshake_failure is None
