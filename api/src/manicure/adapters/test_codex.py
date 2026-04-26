"""Tests for the Codex websocket request adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest
from mitmproxy.test import tflow

from manicure.codex import CodexAdapter
from manicure.ir import (
    ImageBlock,
    Message,
    SamplingParams,
    SystemPart,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from manicure.overrides import apply_overrides


def _fixture_raw() -> bytes:
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "codex_response_create.json"
    )
    return fixture.read_bytes()


def _fixture_payload() -> dict[str, object]:
    payload = json.loads(_fixture_raw())
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _tool_output_fixture_raw() -> bytes:
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "codex_response_create_tool_outputs.json"
    )
    return fixture.read_bytes()


def _tool_output_fixture_payload() -> dict[str, object]:
    payload = json.loads(_tool_output_fixture_raw())
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _later_turn_fixture_raw() -> bytes:
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "codex_response_create_later_turn.json"
    )
    return fixture.read_bytes()


def _later_turn_fixture_payload() -> dict[str, object]:
    payload = json.loads(_later_turn_fixture_raw())
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _outputs_only_fixture_raw() -> bytes:
    fixture = (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "codex_response_create_outputs_only.json"
    )
    return fixture.read_bytes()


def _outputs_only_fixture_payload() -> dict[str, object]:
    payload = json.loads(_outputs_only_fixture_raw())
    assert isinstance(payload, dict)
    return cast("dict[str, object]", payload)


def _codex_flow() -> Any:
    flow = tflow.twebsocketflow(messages=False)
    flow.request.host = "chatgpt.com"
    flow.request.path = "/backend-api/codex/responses?client=cli"
    return flow


def test_matches_chatgpt_codex_websocket_flow() -> None:
    assert CodexAdapter().matches(_codex_flow()) is True


def test_inbound_request_maps_response_create_fixture_into_ir() -> None:
    fixture = _fixture_payload()
    ir = CodexAdapter().inbound_request(json.dumps(fixture).encode())
    fixture_input = cast("list[dict[str, object]]", fixture["input"])

    assert ir.provider == "codex"
    assert ir.model == "codex/gpt-5-codex"
    assert ir.system[0].text == "You are Codex. Be concise."
    assert ir.metadata.session_id == "sess-123"
    assert ir.metadata.device_id == "dev-456"
    assert ir.stream is True

    user_message = ir.messages[0]
    assert user_message.role == "user"
    assert isinstance(user_message.content[0], TextBlock)
    assert user_message.content[0].text == "Review the failing test."
    assert isinstance(user_message.content[1], ImageBlock)
    assert user_message.content[1].source["image_url"].startswith("data:image/png")

    assistant_message = ir.messages[1]
    assert assistant_message.role == "assistant"
    assert isinstance(assistant_message.content[0], TextBlock)
    assert assistant_message.content[0].text == "I need the stack trace."

    reasoning_message = ir.messages[2]
    assert reasoning_message.role == "assistant"
    assert isinstance(reasoning_message.content[0], ThinkingBlock)
    assert reasoning_message.content[0].text == "Inspecting the test failure."
    assert reasoning_message.content[0].provider_data == {
        "id": "rs_123",
        "encrypted_content": "enc_123",
    }

    tool_use_message = ir.messages[3]
    assert tool_use_message.role == "assistant"
    assert isinstance(tool_use_message.content[0], ToolUseBlock)
    assert tool_use_message.content[0].id == "call_read"
    assert tool_use_message.content[0].input == {"path": "README.md"}

    tool_result_message = ir.messages[4]
    assert tool_result_message.role == "user"
    assert isinstance(tool_result_message.content[0], ToolResultBlock)
    assert tool_result_message.content[0].tool_use_id == "call_read"
    assert tool_result_message.content[0].content == [TextBlock(text="README contents")]

    assert ir.tools[0].name == "read_file"
    assert ir.tools[0].input_schema["required"] == ["path"]
    assert ir.tools[0].provider_data == {"type": "function", "strict": False}
    assert ir.tools[1].name == "file_search"
    assert ir.tools[1].provider_data == {
        "type": "file_search",
        "vector_store_ids": ["vs_123"],
    }

    assert ir.sampling.max_tokens == 2048
    assert ir.sampling.temperature == 0.2
    assert ir.sampling.top_p == 0.95
    assert ir.provider_extras["type"] == "response.create"
    assert ir.provider_extras["tool_choice"] == "auto"
    assert ir.provider_extras["parallel_tool_calls"] is True
    assert ir.provider_extras["reasoning"] == {"effort": "high", "summary": "auto"}
    assert ir.provider_extras["input_item_raw"] == [
        {
            "index": 1,
            "raw": fixture_input[1],
        },
        {
            "index": 3,
            "raw": fixture_input[3],
        },
        {
            "index": 4,
            "raw": fixture_input[4],
        },
    ]


def test_inbound_request_handles_sparse_payloads_loss_tolerantly() -> None:
    raw = json.dumps(
        {
            "type": "response.create",
            "model": "gpt-5-codex-mini",
            "input": [{"type": "function_call", "call_id": "call_1", "name": "bash"}],
            "tools": [],
        }
    ).encode()

    ir = CodexAdapter().inbound_request(raw)

    assert ir.model == "codex/gpt-5-codex-mini"
    assert ir.system == []
    assert ir.sampling.max_tokens == 0
    assert ir.messages[0].role == "assistant"
    assert isinstance(ir.messages[0].content[0], ToolUseBlock)
    assert ir.messages[0].content[0].input == {}


def test_outbound_request_round_trips_response_create_fixture() -> None:
    payload = _fixture_payload()
    adapter = CodexAdapter()

    ir = adapter.inbound_request(json.dumps(payload).encode())
    result = json.loads(adapter.outbound_request(ir).decode())

    assert result == payload
    assert (
        cast("dict[str, object]", result["input"][4])["type"] == "function_call_output"
    )


def test_outbound_request_round_trips_client_tool_search_parameters() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "number",
                "description": "Maximum number of tools to return.",
            },
            "query": {
                "type": "string",
                "description": "Search query for deferred tools.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    payload: dict[str, object] = {
        "type": "response.create",
        "model": "gpt-5.4",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "Find GitHub tools."}],
            }
        ],
        "tools": [
            {
                "type": "tool_search",
                "execution": "client",
                "description": "Search deferred tool metadata.",
                "parameters": schema,
            }
        ],
    }
    adapter = CodexAdapter()

    ir = adapter.inbound_request(json.dumps(payload).encode())
    result = json.loads(adapter.outbound_request(ir).decode())

    assert ir.tools[0].name == "tool_search"
    assert ir.tools[0].input_schema == schema
    assert ir.tools[0].provider_data == {
        "type": "tool_search",
        "execution": "client",
    }
    tool = cast("dict[str, object]", cast("list[object]", result["tools"])[0])
    assert tool["parameters"] == schema
    assert "input_schema" not in tool
    assert result == payload


def test_outbound_request_round_trips_tool_search_output() -> None:
    payload: dict[str, object] = {
        "type": "response.create",
        "model": "gpt-5.5",
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
    adapter = CodexAdapter()

    ir = adapter.inbound_request(json.dumps(payload).encode())
    result = json.loads(adapter.outbound_request(ir).decode())

    assert len(ir.messages) == 1
    block = cast("ToolResultBlock", ir.messages[0].content[0])
    assert block.type == "tool_result"
    assert block.tool_use_id == "call_search"
    assert len(block.content) == 1
    assert isinstance(block.content[0], TextBlock)
    assert "fmm_list_files" in block.content[0].text
    assert block.provider_data is not None
    assert block.provider_data["type"] == "tool_search_output"
    assert "input_item_raw" not in ir.provider_extras
    assert result == payload


def test_outbound_request_round_trips_custom_tool_output_fixture() -> None:
    payload = _tool_output_fixture_payload()
    adapter = CodexAdapter()

    ir = adapter.inbound_request(json.dumps(payload).encode())
    result = json.loads(adapter.outbound_request(ir).decode())

    assert result == payload
    custom_tool_result = cast("ToolResultBlock", ir.messages[4].content[0])
    assert custom_tool_result.provider_data == {"type": "custom_tool_call_output"}
    assert ir.provider_extras["input_item_raw"] == [
        {
            "index": 4,
            "raw": cast("list[dict[str, object]]", payload["input"])[4],
        }
    ]
    assert (
        cast("dict[str, object]", result["input"][2])["type"] == "function_call_output"
    )
    assert cast("dict[str, object]", result["input"][4])["type"] == (
        "custom_tool_call_output"
    )


def test_outbound_request_preserves_codex_raw_fields_while_serializing_edits() -> None:
    adapter = CodexAdapter()
    ir = adapter.inbound_request(_fixture_raw())

    edited_messages = list(ir.messages)
    edited_messages[0] = Message(
        role="user",
        content=[
            TextBlock(text="Review only the failing assertion."),
            cast("ImageBlock", edited_messages[0].content[1]),
        ],
    )
    edited_messages[1] = Message(
        role="assistant",
        content=[TextBlock(text="Show me the traceback first.")],
    )
    edited_messages[3] = Message(
        role="assistant",
        content=[
            ToolUseBlock(
                id="call_read",
                name="read_file",
                input={"path": "docs/README.md"},
            )
        ],
    )
    edited_messages[4] = Message(
        role="user",
        content=[
            ToolResultBlock(
                tool_use_id="call_read",
                content=[TextBlock(text="Updated README contents")],
            )
        ],
    )

    edited_ir = ir.model_copy(
        update={
            "system": [SystemPart(text="You are Codex. Keep the diff tight.")],
            "messages": edited_messages,
            "sampling": SamplingParams(
                max_tokens=1024,
                temperature=0.6,
                top_p=ir.sampling.top_p,
                top_k=ir.sampling.top_k,
                stop_sequences=ir.sampling.stop_sequences,
            ),
            "provider_extras": {
                **ir.provider_extras,
                "reasoning": {"effort": "medium", "summary": "auto"},
            },
        }
    )

    payload = json.loads(adapter.outbound_request(edited_ir).decode())

    assert payload["instructions"] == "You are Codex. Keep the diff tight."
    assert payload["max_output_tokens"] == 1024
    assert payload["temperature"] == 0.6
    assert payload["reasoning"] == {"effort": "medium", "summary": "auto"}

    user_message = cast("dict[str, object]", payload["input"][0])
    assert user_message["role"] == "user"
    assert cast("list[dict[str, object]]", user_message["content"])[0]["text"] == (
        "Review only the failing assertion."
    )

    assistant_message = cast("dict[str, object]", payload["input"][1])
    assert assistant_message["id"] == "msg_prev"
    assert assistant_message["status"] == "completed"
    assistant_content = cast("list[dict[str, object]]", assistant_message["content"])
    assert assistant_content[0]["text"] == "Show me the traceback first."
    assert assistant_content[0]["annotations"] == []

    function_call = cast("dict[str, object]", payload["input"][3])
    assert function_call["id"] == "fc_123"
    assert function_call["call_id"] == "call_read"
    assert function_call["arguments"] == '{"path":"docs/README.md"}'

    function_output = cast("dict[str, object]", payload["input"][4])
    assert function_output["id"] == "fco_123"
    assert function_output["output"] == "Updated README contents"


def test_outbound_request_preserves_custom_tool_output_type_when_editing_output() -> (
    None
):
    adapter = CodexAdapter()
    ir = adapter.inbound_request(_tool_output_fixture_raw())

    edited_messages = list(ir.messages)
    function_result = cast("ToolResultBlock", edited_messages[2].content[0])
    edited_messages[2] = Message(
        role="user",
        content=[
            function_result.model_copy(
                update={"content": [TextBlock(text="Fresh README contents")]}
            )
        ],
    )
    custom_result = cast("ToolResultBlock", edited_messages[4].content[0])
    edited_messages[4] = Message(
        role="user",
        content=[
            custom_result.model_copy(
                update={"content": [TextBlock(text="workspace/edited")]}
            )
        ],
    )

    payload = json.loads(
        adapter.outbound_request(
            ir.model_copy(update={"messages": edited_messages})
        ).decode()
    )

    function_output = cast("dict[str, object]", payload["input"][2])
    assert function_output["type"] == "function_call_output"
    assert function_output["output"] == "Fresh README contents"

    custom_output = cast("dict[str, object]", payload["input"][4])
    assert custom_output["type"] == "custom_tool_call_output"
    assert custom_output["output"] == "workspace/edited"


def test_outbound_request_round_trips_later_turn_fixture() -> None:
    payload = _later_turn_fixture_payload()
    adapter = CodexAdapter()

    ir = adapter.inbound_request(json.dumps(payload).encode())
    result = json.loads(adapter.outbound_request(ir).decode())

    assert result == payload


def test_noop_override_pipeline_preserves_outputs_only_continuation_turn() -> None:
    payload = _outputs_only_fixture_payload()
    adapter = CodexAdapter()

    ir = adapter.inbound_request(json.dumps(payload).encode())
    curated_ir, audit = apply_overrides([], ir)
    result = json.loads(adapter.outbound_request(curated_ir).decode())

    assert audit.messages_chars_before == audit.messages_chars_after
    assert audit.messages_chars_after > 0
    assert result == payload


def test_outbound_request_edits_later_turn_fixture_without_reconciliation_error() -> (
    None
):
    adapter = CodexAdapter()
    ir = adapter.inbound_request(_later_turn_fixture_raw())

    edited_system = [
        ir.system[0].model_copy(update={"text": "Keep the summary to two words."})
    ]
    edited_messages = list(ir.messages)
    custom_result = cast("ToolResultBlock", edited_messages[2].content[0])
    edited_messages[2] = Message(
        role="user",
        content=[
            custom_result.model_copy(
                update={"content": [TextBlock(text="workspace/edited")]}
            )
        ],
    )

    payload = json.loads(
        adapter.outbound_request(
            ir.model_copy(update={"system": edited_system, "messages": edited_messages})
        ).decode()
    )

    custom_output = cast("dict[str, object]", payload["input"][2])
    assert custom_output["type"] == "custom_tool_call_output"
    assert custom_output["output"] == "workspace/edited"

    developer_message = cast("dict[str, object]", payload["input"][3])
    developer_content = cast("list[dict[str, object]]", developer_message["content"])
    assert developer_message["role"] == "developer"
    assert developer_message["id"] == "msg_dev"
    assert developer_content[0]["text"] == "Keep the summary to two words."


def test_outbound_request_raises_when_preserved_raw_items_cannot_be_reconciled() -> (
    None
):
    adapter = CodexAdapter()
    ir = adapter.inbound_request(_fixture_raw())

    with pytest.raises(
        ValueError,
        match=r"preserved raw input item at index 3",
    ):
        adapter.outbound_request(
            ir.model_copy(
                update={
                    "messages": ir.messages[:3],
                }
            )
        )


def test_round_trip_preserves_system_message_order_using_raw_indices() -> None:
    payload = {
        "type": "response.create",
        "model": "gpt-5-codex",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "first"}],
            },
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": "guardrail"}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "second"}],
            },
        ],
        "tools": [],
    }

    adapter = CodexAdapter()
    ir = adapter.inbound_request(json.dumps(payload).encode())
    result = json.loads(adapter.outbound_request(ir).decode())

    assert ir.provider_extras["input_item_raw"] == [
        {"index": 1, "raw": payload["input"][1]},
    ]
    assert result == payload


def test_outbound_request_round_trips_refusal_content_with_preserved_raw() -> None:
    payload = {
        "type": "response.create",
        "model": "gpt-5-codex",
        "input": [
            {
                "role": "assistant",
                "id": "msg_refusal",
                "content": [
                    {
                        "type": "refusal",
                        "refusal": "I can't help with that.",
                        "annotations": [],
                    }
                ],
            }
        ],
        "tools": [],
    }

    adapter = CodexAdapter()
    ir = adapter.inbound_request(json.dumps(payload).encode())
    result = json.loads(adapter.outbound_request(ir).decode())

    assert result == payload


def test_outbound_request_updates_refusal_text_without_emitting_text_key() -> None:
    payload = {
        "type": "response.create",
        "model": "gpt-5-codex",
        "input": [
            {
                "role": "assistant",
                "id": "msg_refusal",
                "content": [
                    {
                        "type": "refusal",
                        "refusal": "I can't help with that.",
                        "annotations": [],
                    }
                ],
            }
        ],
        "tools": [],
    }

    adapter = CodexAdapter()
    ir = adapter.inbound_request(json.dumps(payload).encode())
    edited_ir = ir.model_copy(
        update={
            "messages": [
                Message(
                    role="assistant",
                    content=[TextBlock(text="I still can't help with that.")],
                )
            ]
        }
    )

    result = json.loads(adapter.outbound_request(edited_ir).decode())
    content = cast("list[dict[str, object]]", result["input"][0]["content"])

    assert content == [
        {
            "type": "refusal",
            "refusal": "I still can't help with that.",
            "annotations": [],
        }
    ]
