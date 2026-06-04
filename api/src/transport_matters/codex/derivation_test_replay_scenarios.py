"""Codex derivation replay scenario fixtures."""

from transport_matters.codex.derivation import CodexReplayRequest

from .derivation_test_builders import make_close, make_context, make_message


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
