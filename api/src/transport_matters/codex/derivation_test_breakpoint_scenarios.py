"""Breakpoint edited Codex derivation replay fixtures."""

from transport_matters.codex.derivation import (
    CodexDerivationOperatorFact,
    CodexReplayRequest,
    CodexTransportMessageFact,
)

from .derivation_test_builders import make_context, make_message, ts


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
