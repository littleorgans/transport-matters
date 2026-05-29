"""Codex response.create request serialization from Transport Matters IR."""

from __future__ import annotations

import json
from typing import Any

from transport_matters.codex.preserved_raw import (
    SerializedInputItem,
    apply_preserved_input_items,
    input_item_kind,
    looks_like_input_item,
    materialize_input_items,
    parse_preserved_input_item_raw,
)
from transport_matters.codex.protocol import (
    CODEX_IMAGE_TYPE,
    CODEX_INPUT_TEXT_TYPE,
    CODEX_MODEL_PREFIX,
    CODEX_OUTPUT_TEXT_TYPE,
    CODEX_TOOL_OUTPUT_ITEM_TYPES,
    RAW_TOOL_ARGUMENTS_KEY,
)
from transport_matters.ir import (
    ContentBlock,
    ImageBlock,
    InternalRequest,
    Message,
    RequestMetadata,
    SystemPart,
    TextBlock,
    ThinkingBlock,
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
)
from transport_matters.model_ids import denormalise_model


def serialize_codex_request(ir: InternalRequest) -> bytes:
    extras = dict(ir.provider_extras)
    preserved_input = parse_preserved_input_item_raw(extras.pop("input_item_raw", []))

    data: dict[str, Any] = dict(extras)
    # Only emit the WS envelope `type: "response.create"` field if the inbound
    # request had one. Codex's HTTPS Responses fallback transport uses the raw
    # `ResponsesApiRequest` shape with no top-level `type`; the upstream rejects
    # the field with `Unsupported parameter: type`. WS bodies carry the field
    # through via `provider_extras`, so round-trip parity is preserved.
    if "type" in data:
        data["type"] = str(data["type"])
    data["model"] = denormalise_model(ir.model, CODEX_MODEL_PREFIX)

    instructions, input_items = _serialize_input(
        ir.system, ir.messages, preserved_input
    )
    if instructions is not None:
        data["instructions"] = instructions
    data["input"] = input_items
    data["tools"] = [_tool_to_dict(tool) for tool in ir.tools]

    metadata = _metadata_to_dict(ir.metadata)
    if metadata:
        data["client_metadata"] = metadata

    if ir.stream:
        data["stream"] = True
    if ir.sampling.temperature is not None:
        data["temperature"] = ir.sampling.temperature
    if ir.sampling.top_p is not None:
        data["top_p"] = ir.sampling.top_p
    if ir.sampling.top_k is not None:
        data["top_k"] = ir.sampling.top_k
    if ir.sampling.max_tokens > 0:
        data["max_output_tokens"] = ir.sampling.max_tokens
    if ir.sampling.stop_sequences:
        data["stop_sequences"] = ir.sampling.stop_sequences

    return json.dumps(data, separators=(",", ":"), sort_keys=True).encode()


def _serialize_input(
    system: list[SystemPart],
    messages: list[Message],
    preserved_input: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    instruction_parts: list[str] = []
    items: list[SerializedInputItem] = []

    for part in system:
        provider_data = (
            dict(part.provider_data) if isinstance(part.provider_data, dict) else {}
        )
        role = provider_data.get("role")
        if role in {"system", "developer"}:
            content: dict[str, Any] = {"type": CODEX_INPUT_TEXT_TYPE, "text": part.text}
            for key, value in provider_data.items():
                if key != "role":
                    content[key] = value
            items.append(
                SerializedInputItem(
                    kind=f"message:{role}",
                    payload={"role": role, "content": [content]},
                )
            )
            continue
        instruction_parts.append(part.text)

    for message in messages:
        items.extend(_serialize_message(message))

    apply_preserved_input_items(items, preserved_input)
    instructions = "\n\n".join(part for part in instruction_parts if part) or None
    return instructions, materialize_input_items(items)


def _serialize_message(message: Message) -> list[SerializedInputItem]:
    if len(message.content) == 1:
        block = message.content[0]
        if isinstance(block, ToolUseBlock):
            return [
                SerializedInputItem(kind="tool_use", payload=_tool_use_to_dict(block))
            ]
        if isinstance(block, ToolResultBlock):
            return [
                SerializedInputItem(
                    kind=_tool_result_kind(block),
                    payload=_tool_result_to_dict(block),
                )
            ]
        if isinstance(block, ThinkingBlock):
            return [
                SerializedInputItem(kind="reasoning", payload=_thinking_to_dict(block))
            ]
        if isinstance(block, UnknownBlock) and looks_like_input_item(block.raw):
            return [
                SerializedInputItem(
                    kind=input_item_kind(block.raw),
                    payload=dict(block.raw),
                )
            ]

    unsupported = [
        block.type
        for block in message.content
        if isinstance(
            block, (ToolUseBlock, ToolResultBlock, ThinkingBlock, UnknownBlock)
        )
    ]
    if unsupported:
        raise ValueError(
            "Codex serializer cannot safely emit message with blocks: "
            + ", ".join(sorted(set(unsupported)))
        )

    return [
        SerializedInputItem(
            kind=f"message:{message.role}",
            payload={
                "role": message.role,
                "content": [
                    _message_content_to_dict(message.role, block)
                    for block in message.content
                ],
            },
        )
    ]


def _message_content_to_dict(
    role: str,
    block: ContentBlock,
) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        text_type = (
            CODEX_OUTPUT_TEXT_TYPE if role == "assistant" else CODEX_INPUT_TEXT_TYPE
        )
        return {"type": text_type, "text": block.text}
    if isinstance(block, ImageBlock) and role == "user":
        return {"type": CODEX_IMAGE_TYPE, **block.source}
    if isinstance(block, UnknownBlock):
        # Forward-compat: preserve an unmodeled sub-block verbatim rather than
        # crashing serialization (matches the Anthropic adapter's degradation).
        return block.raw
    raise ValueError(
        f"Codex serializer cannot encode {block.type!r} inside {role!r} message"
    )


def _tool_use_to_dict(block: ToolUseBlock) -> dict[str, Any]:
    arguments = block.input
    if set(arguments) == {RAW_TOOL_ARGUMENTS_KEY} and isinstance(
        arguments[RAW_TOOL_ARGUMENTS_KEY], str
    ):
        encoded_arguments: object = arguments[RAW_TOOL_ARGUMENTS_KEY]
    else:
        encoded_arguments = json.dumps(arguments, separators=(",", ":"), sort_keys=True)
    return {
        "type": "function_call",
        "call_id": block.id,
        "name": block.name,
        "arguments": encoded_arguments,
    }


def _tool_result_to_dict(block: ToolResultBlock) -> dict[str, Any]:
    wire_type = "function_call_output"
    if isinstance(block.provider_data, dict):
        raw_type = block.provider_data.get("type")
        if raw_type in CODEX_TOOL_OUTPUT_ITEM_TYPES:
            wire_type = str(raw_type)
    if wire_type == "tool_search_output":
        provider_data: dict[str, Any] = (
            block.provider_data if isinstance(block.provider_data, dict) else {}
        )
        payload: dict[str, Any] = {
            "type": wire_type,
            "call_id": block.tool_use_id,
            "tools": provider_data.get("tools", []),
        }
        for key in ("status", "execution"):
            value = provider_data.get(key)
            if isinstance(value, str):
                payload[key] = value
        return payload
    if len(block.content) == 1 and isinstance(block.content[0], TextBlock):
        output: object = block.content[0].text
    elif len(block.content) == 0:
        output = ""
    else:
        output = [_message_content_to_dict("user", item) for item in block.content]

    output_payload: dict[str, Any] = {
        "type": wire_type,
        "call_id": block.tool_use_id,
        "output": output,
    }
    if block.is_error:
        output_payload["is_error"] = True
    return output_payload


def _tool_result_kind(block: ToolResultBlock) -> str:
    payload = _tool_result_to_dict(block)
    return f"tool_result:{payload['type']}"


def _thinking_to_dict(block: ThinkingBlock) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "reasoning"}
    if block.provider_data:
        payload.update(block.provider_data)
    payload["summary"] = (
        [{"type": "summary_text", "text": block.text}] if block.text else []
    )
    return payload


def _tool_to_dict(tool: ToolDef) -> dict[str, Any]:
    payload: dict[str, Any] = dict(tool.provider_data or {})
    tool_type = str(payload.get("type", "function"))
    payload["type"] = tool_type

    if tool_type == "function" or tool.name != tool_type:
        payload["name"] = tool.name
    if tool_type == "function" or tool.description:
        payload["description"] = tool.description

    if tool_type == "function" or (
        tool_type == "tool_search" and payload.get("execution") == "client"
    ):
        payload["parameters"] = tool.input_schema

    return payload


def _metadata_to_dict(meta: RequestMetadata) -> dict[str, Any]:
    payload = dict(meta.provider_metadata)

    for names, value in (
        (("session_id", "sessionId"), meta.session_id),
        (("device_id", "deviceId"), meta.device_id),
        (("account_id", "accountId"), meta.account_id),
    ):
        if value is None:
            continue
        key = next((name for name in names if name in payload), names[0])
        payload[key] = value

    return payload
