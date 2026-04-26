"""Shared builders for Codex derivation tests."""

from __future__ import annotations

from datetime import UTC, datetime

from manicure.codex.derivation import (
    CODEX_DERIVATION_VERSION,
    CodexDerivationOperatorFact,
    CodexReplayRequest,
    CodexTransportCloseFact,
    CodexTransportMessageFact,
    CodexTurnDerivationContext,
)
from manicure.codex.events import (
    CodexDerivationCursor,
    CodexSemanticEvent,
    CodexTransportRef,
    CodexTurnSummary,
)


def ts(hour: int, minute: int, second: int) -> datetime:
    return datetime(2026, 4, 19, hour, minute, second, tzinfo=UTC)


def make_context(**overrides: object) -> CodexTurnDerivationContext:
    values: dict[str, object] = {
        "exchange_id": "ex_123",
        "session_id": "ws_abc",
        "turn_id": "turn_002",
        "turn_index": 2,
        "request_message_index": 23,
        "model": "codex/gpt-5-codex",
        "derivation_version": CODEX_DERIVATION_VERSION,
    }
    values.update(overrides)
    return CodexTurnDerivationContext(**values)


def make_message(
    message_index: int,
    hour: int,
    minute: int,
    second: int,
    *,
    direction: str,
    event_type: str,
    payload_json: dict[str, object] | None = None,
    dropped: bool = False,
) -> CodexTransportMessageFact:
    payload = payload_json or {"type": event_type}
    return CodexTransportMessageFact(
        message_index=message_index,
        ts=ts(hour, minute, second),
        direction=direction,
        event_type=event_type,
        payload_json=payload,
        dropped=dropped,
    )


def make_cursor(**overrides: object) -> CodexDerivationCursor:
    values: dict[str, object] = {
        "next_message_index": 24,
        "next_seq": 2,
        "open_assistant_items": {},
        "open_tool_calls": {},
        "terminal_seen": False,
    }
    values.update(overrides)
    return CodexDerivationCursor(**values)


def make_close(
    hour: int,
    minute: int,
    second: int,
    *,
    close_code: int | None = 1006,
) -> CodexTransportCloseFact:
    return CodexTransportCloseFact(
        ts=ts(hour, minute, second),
        close_code=close_code,
    )


def make_event(
    seq: int,
    kind: str,
    event_ts: datetime,
    **overrides: object,
) -> CodexSemanticEvent:
    values: dict[str, object] = {
        "event_id": f"evt_{seq:06d}",
        "exchange_id": "ex_123",
        "session_id": "ws_abc",
        "turn_id": "turn_002",
        "seq": seq,
        "ts": event_ts,
        "source": "server",
        "kind": kind,
        "transport_ref": CodexTransportRef(message_index=22 + seq),
        "derivation_version": CODEX_DERIVATION_VERSION,
    }
    values.update(overrides)
    return CodexSemanticEvent(**values)


def make_completed_turn(**overrides: object) -> CodexTurnSummary:
    values: dict[str, object] = {
        "turn_id": "turn_002",
        "exchange_id": "ex_123",
        "session_id": "ws_abc",
        "turn_index": 2,
        "request_message_index": 23,
        "terminal_message_index": 25,
        "terminal_cause": "response_completed",
        "message_range_start": 23,
        "message_range_end": 25,
        "model": "codex/gpt-5-codex",
        "status": "completed",
        "stop_reason": "completed",
        "text_chars": 42,
        "tool_calls": 0,
        "started_at": ts(10, 14, 3),
        "ended_at": ts(10, 14, 6),
        "derivation_version": CODEX_DERIVATION_VERSION,
    }
    values.update(overrides)
    return CodexTurnSummary(**values)


def make_single_turn_success_request() -> CodexReplayRequest:
    return CodexReplayRequest(
        context=make_context(
            exchange_id="ex_single",
            session_id="ws_single",
            turn_id="turn_000",
            turn_index=0,
            request_message_index=0,
        ),
        transport_messages=[
            make_message(
                0,
                10,
                14,
                0,
                direction="client",
                event_type="response.create",
                payload_json={
                    "type": "response.create",
                    "model": "gpt-5-codex",
                },
            ),
            make_message(
                1,
                10,
                14,
                1,
                direction="server",
                event_type="response.output_item.done",
                payload_json={
                    "type": "response.output_item.done",
                    "item": {
                        "id": "msg_00",
                        "type": "message",
                        "status": "completed",
                        "phase": "final_answer",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "hello world",
                            }
                        ],
                    },
                },
            ),
            make_message(
                2,
                10,
                14,
                2,
                direction="server",
                event_type="response.completed",
                payload_json={
                    "type": "response.completed",
                    "response": {
                        "id": "resp_single",
                        "status": "completed",
                    },
                },
            ),
        ],
    )


def _breakpoint_edited_operator_facts() -> list[CodexDerivationOperatorFact]:
    return [
        CodexDerivationOperatorFact(
            kind="request_curated",
            ts=ts(10, 14, 2),
        ),
        CodexDerivationOperatorFact(
            kind="breakpoint_paused",
            ts=ts(10, 14, 2),
            data={"flow_id": "flow_breakpoint"},
        ),
        CodexDerivationOperatorFact(
            kind="breakpoint_released",
            ts=ts(10, 14, 3),
            data={"flow_id": "flow_breakpoint"},
        ),
    ]


def _breakpoint_edited_transport_messages() -> list[CodexTransportMessageFact]:
    return [
        make_message(
            23,
            10,
            14,
            4,
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
            5,
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
            6,
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
            7,
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
            8,
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
            9,
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
            10,
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
            11,
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
    ]


def make_breakpoint_edited_turn_request() -> CodexReplayRequest:
    return CodexReplayRequest(
        context=make_context(
            exchange_id="ex_breakpoint",
            session_id="ws_breakpoint",
            turn_id="turn_breakpoint",
            turn_index=3,
            request_message_index=23,
        ),
        operator_facts=_breakpoint_edited_operator_facts(),
        transport_messages=_breakpoint_edited_transport_messages(),
    )


def make_failed_turn_request() -> CodexReplayRequest:
    return CodexReplayRequest(
        context=make_context(
            exchange_id="ex_failed",
            session_id="ws_failed",
            turn_id="turn_failed",
            turn_index=1,
            request_message_index=0,
        ),
        transport_messages=[
            make_message(
                0,
                10,
                15,
                0,
                direction="client",
                event_type="response.create",
                payload_json={
                    "type": "response.create",
                    "model": "gpt-5-codex",
                },
            ),
            make_message(
                1,
                10,
                15,
                1,
                direction="server",
                event_type="response.failed",
                payload_json={
                    "type": "response.failed",
                    "response": {
                        "id": "resp_failed",
                        "status": "failed",
                    },
                },
            ),
        ],
    )


def make_interrupted_turn_request() -> CodexReplayRequest:
    return CodexReplayRequest(
        context=make_context(
            exchange_id="ex_interrupted",
            session_id="ws_interrupted",
            turn_id="turn_interrupted",
            turn_index=2,
            request_message_index=0,
        ),
        transport_messages=[
            make_message(
                0,
                10,
                16,
                0,
                direction="client",
                event_type="response.create",
                payload_json={
                    "type": "response.create",
                    "model": "gpt-5-codex",
                },
            ),
            make_message(
                1,
                10,
                16,
                1,
                direction="server",
                event_type="response.output_text.delta",
                payload_json={
                    "type": "response.output_text.delta",
                    "item_id": "msg_partial",
                    "delta": "hello",
                },
            ),
        ],
        close=make_close(10, 16, 2, close_code=1006),
    )


def make_handshake_failure_request() -> CodexReplayRequest:
    return CodexReplayRequest(
        context=make_context(
            exchange_id="ex_handshake",
            session_id="ws_handshake",
            turn_id="turn_missing",
            turn_index=0,
            request_message_index=0,
        ),
        transport_messages=[
            make_message(
                0,
                10,
                17,
                0,
                direction="server",
                event_type="response.failed",
                payload_json={
                    "type": "response.failed",
                    "response": {"status": "failed"},
                },
            )
        ],
    )


def make_dropped_initial_frame_request() -> CodexReplayRequest:
    return CodexReplayRequest(
        context=make_context(
            exchange_id="ex_dropped",
            session_id="ws_dropped",
            turn_id="turn_dropped",
            turn_index=0,
            request_message_index=0,
        ),
        transport_messages=[
            make_message(
                0,
                10,
                18,
                0,
                direction="client",
                event_type="response.create",
                payload_json={
                    "type": "response.create",
                    "model": "gpt-5-codex",
                },
                dropped=True,
            ),
        ],
        close=make_close(10, 18, 1, close_code=1000),
    )


def make_tool_result_only_continuation_request() -> CodexReplayRequest:
    return CodexReplayRequest(
        context=make_context(
            exchange_id="ex_tool_result",
            session_id="ws_tool_result",
            turn_id="turn_tool_result",
            turn_index=5,
            request_message_index=0,
        ),
        transport_messages=[
            make_message(
                0,
                10,
                19,
                0,
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
                1,
                10,
                19,
                1,
                direction="server",
                event_type="response.completed",
                payload_json={
                    "type": "response.completed",
                    "response": {"status": "completed"},
                },
            ),
        ],
    )


def make_multi_turn_success_requests() -> tuple[CodexReplayRequest, CodexReplayRequest]:
    full_transport = [
        make_message(
            0,
            10,
            20,
            0,
            direction="client",
            event_type="response.create",
            payload_json={
                "type": "response.create",
                "model": "gpt-5-codex",
            },
        ),
        make_message(
            1,
            10,
            20,
            1,
            direction="server",
            event_type="response.output_item.done",
            payload_json={
                "type": "response.output_item.done",
                "item": {
                    "id": "msg_first",
                    "type": "message",
                    "status": "completed",
                    "phase": "final_answer",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "first"}],
                },
            },
        ),
        make_message(
            2,
            10,
            20,
            2,
            direction="server",
            event_type="response.completed",
            payload_json={
                "type": "response.completed",
                "response": {"id": "resp_first", "status": "completed"},
            },
        ),
        make_message(
            3,
            10,
            20,
            3,
            direction="client",
            event_type="response.create",
            payload_json={
                "type": "response.create",
                "model": "gpt-5-codex",
            },
        ),
        make_message(
            4,
            10,
            20,
            4,
            direction="server",
            event_type="response.output_item.done",
            payload_json={
                "type": "response.output_item.done",
                "item": {
                    "id": "msg_second",
                    "type": "message",
                    "status": "completed",
                    "phase": "final_answer",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "second"}],
                },
            },
        ),
        make_message(
            5,
            10,
            20,
            5,
            direction="server",
            event_type="response.completed",
            payload_json={
                "type": "response.completed",
                "response": {"id": "resp_second", "status": "completed"},
            },
        ),
    ]

    first = CodexReplayRequest(
        context=make_context(
            exchange_id="ex_multi_first",
            session_id="ws_multi",
            turn_id="turn_multi_000",
            turn_index=0,
            request_message_index=0,
        ),
        transport_messages=full_transport[:3],
    )
    second = CodexReplayRequest(
        context=make_context(
            exchange_id="ex_multi_second",
            session_id="ws_multi",
            turn_id="turn_multi_001",
            turn_index=1,
            request_message_index=3,
        ),
        transport_messages=full_transport[3:],
    )
    return first, second
