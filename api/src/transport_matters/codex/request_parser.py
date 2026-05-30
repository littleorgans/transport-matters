"""Codex response.create request parsing into Transport Matters IR."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from transport_matters.codex.protocol import (
    CODEX_IMAGE_TYPE,
    CODEX_INPUT_TEXT_TYPES,
    CODEX_MODEL_PREFIX,
    CODEX_OUTPUT_TEXT_TYPES,
    CODEX_REFUSAL_TYPE,
    CODEX_TOOL_OUTPUT_ITEM_TYPES,
    decode_tool_arguments,
)
from transport_matters.ir import (
    ContentBlock,
    ImageBlock,
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
    ThinkingBlock,
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
)
from transport_matters.model_ids import normalise_model

_ContentParseResult = tuple[ContentBlock, bool]
_ContentHandler = Callable[[dict[str, Any]], _ContentParseResult | None]

MAPPED_REQUEST_KEYS = frozenset(
    {
        "model",
        "instructions",
        "input",
        "tools",
        "client_metadata",
        "stream",
        "temperature",
        "top_p",
        "top_k",
        "max_output_tokens",
        "stop",
        "stop_sequences",
    }
)
STANDARD_FUNCTION_CALL_OUTPUT_KEYS = frozenset({"type", "call_id", "output"})
STANDARD_TOOL_SEARCH_OUTPUT_KEYS = frozenset(
    {"type", "call_id", "status", "execution", "tools"}
)


def parse_codex_request(raw_body: bytes) -> InternalRequest:
    data = json.loads(raw_body)
    if not isinstance(data, dict):
        raise ValueError("Codex frame must be a JSON object")
    if data.get("type") not in (None, "response.create"):
        raise ValueError(
            f"Codex request parser expected response.create, got {data.get('type')!r}"
        )

    system = _parse_instructions(data.get("instructions"))
    input_system, messages, input_item_raw = _parse_input(data.get("input", []))
    system.extend(input_system)

    extras: dict[str, Any] = {
        key: value for key, value in data.items() if key not in MAPPED_REQUEST_KEYS
    }
    if input_item_raw:
        extras["input_item_raw"] = input_item_raw

    return InternalRequest(
        model=normalise_model(str(data.get("model", "unknown")), CODEX_MODEL_PREFIX),
        provider="codex",
        system=system,
        tools=_parse_tools(data.get("tools", [])),
        messages=messages or [Message(role="user", content=[])],
        sampling=_parse_sampling(data),
        metadata=_parse_metadata(data.get("client_metadata")),
        stream=bool(data.get("stream", False)),
        provider_extras=extras,
    )


def _parse_instructions(raw: object) -> list[SystemPart]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [SystemPart(text=raw)] if raw else []
    return [SystemPart(text=json.dumps(raw, sort_keys=True))]


def _parse_input(
    raw: object,
) -> tuple[list[SystemPart], list[Message], list[dict[str, Any]]]:
    if isinstance(raw, str):
        return [], [Message(role="user", content=[TextBlock(text=raw)])], []
    if isinstance(raw, dict):
        items: list[Any] = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        return [], [], []

    system: list[SystemPart] = []
    messages: list[Message] = []
    preserved_raw: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            messages.append(
                Message(role="user", content=[UnknownBlock(raw={"value": item})])
            )
            preserved_raw.append({"index": index, "raw": item})
            continue

        item_type = item.get("type")
        if item_type == "message" or "role" in item:
            added_system, added_messages, keep_raw = _parse_message_item(item)
            system.extend(added_system)
            messages.extend(added_messages)
            if keep_raw:
                preserved_raw.append({"index": index, "raw": item})
            continue
        if item_type == "function_call":
            messages.append(_parse_function_call(item))
            if set(item) - {"type", "call_id", "name", "arguments"}:
                preserved_raw.append({"index": index, "raw": item})
            continue
        if item_type in CODEX_TOOL_OUTPUT_ITEM_TYPES:
            messages.append(_parse_function_call_output(item))
            if _should_preserve_tool_output_raw(item):
                preserved_raw.append({"index": index, "raw": item})
            continue
        if item_type == "reasoning":
            messages.append(_parse_reasoning_item(item))
            continue

        messages.append(Message(role="assistant", content=[UnknownBlock(raw=item)]))
        preserved_raw.append({"index": index, "raw": item})

    return system, messages, preserved_raw


def _should_preserve_tool_output_raw(item: dict[str, Any]) -> bool:
    item_type = item.get("type")
    if item_type == "function_call_output":
        return bool(set(item) - STANDARD_FUNCTION_CALL_OUTPUT_KEYS)
    if item_type == "tool_search_output":
        return bool(set(item) - STANDARD_TOOL_SEARCH_OUTPUT_KEYS)
    return True


def _parse_message_item(
    item: dict[str, Any],
) -> tuple[list[SystemPart], list[Message], bool]:
    role = item.get("role", "user")
    raw_content = item.get("content", [])

    if role in {"system", "developer"}:
        system, keep_raw = _parse_system_message_item(item, raw_content)
        return system, [], keep_raw

    if role == "assistant":
        content, keep_raw = _parse_assistant_content(raw_content)
        message_role = "assistant"
    else:
        content, keep_raw = _parse_user_content(raw_content)
        message_role = "user"

    if not content and raw_content is not None:
        keep_raw = True

    extra_fields = set(item) - {"type", "role", "content"}
    return (
        [],
        [Message(role=message_role, content=content)],
        bool(keep_raw or extra_fields),
    )


def _parse_system_message_item(
    item: dict[str, Any], raw_content: object
) -> tuple[list[SystemPart], bool]:
    if isinstance(raw_content, str):
        return [
            SystemPart(text=raw_content, provider_data={"role": item["role"]})
        ], True
    if not isinstance(raw_content, list):
        return [], True

    parts: list[SystemPart] = []
    for entry in raw_content:
        if not isinstance(entry, dict):
            continue
        entry_type = entry.get("type")
        if entry_type in CODEX_INPUT_TEXT_TYPES and isinstance(entry.get("text"), str):
            provider_data: dict[str, Any] = {"role": item["role"]}
            extra = set(entry) - {"type", "text"}
            if extra:
                provider_data.update({key: entry[key] for key in sorted(extra)})
            parts.append(SystemPart(text=entry["text"], provider_data=provider_data))
    return parts, True


def _parse_content(
    raw_content: object,
    *,
    text_types: frozenset[str],
    extra_block_handlers: tuple[_ContentHandler, ...],
) -> tuple[list[ContentBlock], bool]:
    if isinstance(raw_content, str):
        return [TextBlock(text=raw_content)], False
    if not isinstance(raw_content, list):
        return [UnknownBlock(raw={"content": raw_content})], True

    blocks: list[ContentBlock] = []
    keep_raw = False
    for item in raw_content:
        if not isinstance(item, dict):
            blocks.append(UnknownBlock(raw={"value": item}))
            keep_raw = True
            continue
        item_type = item.get("type")
        if item_type in text_types and isinstance(item.get("text"), str):
            blocks.append(TextBlock(text=item["text"]))
            if set(item) - {"type", "text"}:
                keep_raw = True
            continue
        for handler in extra_block_handlers:
            result = handler(item)
            if result is None:
                continue
            block, block_keep_raw = result
            blocks.append(block)
            keep_raw = keep_raw or block_keep_raw
            break
        else:
            blocks.append(UnknownBlock(raw=item))
            keep_raw = True
    return blocks, keep_raw


def _parse_assistant_content(raw_content: object) -> tuple[list[ContentBlock], bool]:
    return _parse_content(
        raw_content,
        text_types=CODEX_OUTPUT_TEXT_TYPES,
        extra_block_handlers=(_parse_assistant_extra_block,),
    )


def _parse_user_content(raw_content: object) -> tuple[list[ContentBlock], bool]:
    return _parse_content(
        raw_content,
        text_types=CODEX_INPUT_TEXT_TYPES,
        extra_block_handlers=(_parse_user_extra_block,),
    )


def _parse_user_extra_block(item: dict[str, Any]) -> _ContentParseResult | None:
    if item.get("type") != CODEX_IMAGE_TYPE:
        return None
    source = {key: value for key, value in item.items() if key != "type"}
    return ImageBlock(source=source), False


def _parse_assistant_extra_block(item: dict[str, Any]) -> _ContentParseResult | None:
    if item.get("type") != CODEX_REFUSAL_TYPE or not isinstance(
        item.get("refusal"), str
    ):
        return None
    return TextBlock(text=item["refusal"]), bool(set(item) - {"type", "refusal"})


def _parse_function_call(item: dict[str, Any]) -> Message:
    arguments = item.get("arguments", "{}")
    return Message(
        role="assistant",
        content=[
            ToolUseBlock(
                id=str(item.get("call_id", item.get("id", "tool_call"))),
                name=str(item.get("name", "function_call")),
                input=decode_tool_arguments(arguments),
            )
        ],
    )


def _parse_function_call_output(item: dict[str, Any]) -> Message:
    item_type = item.get("type")
    provider_data = {"type": item_type} if isinstance(item_type, str) else None
    if item_type == "tool_search_output":
        provider_data = dict(provider_data or {})
        for key in ("status", "execution", "tools"):
            if key in item:
                provider_data[key] = item[key]

    output = (
        item.get("tools") if item_type == "tool_search_output" else item.get("output")
    )
    tool_content: list[TextBlock | ImageBlock]
    if item_type == "tool_search_output":
        tool_content = [TextBlock(text=json.dumps(output, indent=2, sort_keys=True))]
    elif isinstance(output, list):
        content, _ = _parse_user_content(output)
        tool_content = [
            block for block in content if isinstance(block, (TextBlock, ImageBlock))
        ]
    elif isinstance(output, str):
        tool_content = [TextBlock(text=output)]
    else:
        tool_content = [TextBlock(text=json.dumps(output, sort_keys=True))]

    return Message(
        role="user",
        content=[
            ToolResultBlock(
                tool_use_id=str(item.get("call_id", "tool_call")),
                content=tool_content or [TextBlock(text="")],
                provider_data=provider_data,
            )
        ],
    )


def _parse_reasoning_item(item: dict[str, Any]) -> Message:
    summary = item.get("summary")
    if isinstance(summary, list):
        text = "\n\n".join(
            part["text"]
            for part in summary
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    else:
        text = ""

    provider_data = {
        key: value for key, value in item.items() if key not in {"type", "summary"}
    } or None
    return Message(
        role="assistant",
        content=[ThinkingBlock(text=text, provider_data=provider_data)],
    )


def _parse_tools(raw: object) -> list[ToolDef]:
    if not isinstance(raw, list):
        return []

    tools: list[ToolDef] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tool_type = str(item.get("type", "function"))
        schema = item.get("parameters")
        if not isinstance(schema, dict):
            schema = item.get("input_schema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}

        extra = {
            key: value
            for key, value in item.items()
            if key not in {"name", "description", "parameters", "input_schema"}
        }
        tools.append(
            ToolDef(
                name=str(item.get("name", tool_type)),
                description=str(item.get("description", "")),
                input_schema=schema,
                provider_data=extra or None,
            )
        )
    return tools


def _parse_metadata(raw: object) -> RequestMetadata:
    if not isinstance(raw, dict):
        return RequestMetadata()

    def string_value(*names: str) -> str | None:
        for name in names:
            value = raw.get(name)
            if isinstance(value, str):
                return value
        return None

    return RequestMetadata(
        session_id=string_value("session_id", "sessionId"),
        device_id=string_value("device_id", "deviceId"),
        account_id=string_value("account_id", "accountId"),
        provider_metadata=dict(raw),
    )


def _parse_sampling(data: dict[str, Any]) -> SamplingParams:
    stop_value = data.get("stop_sequences", data.get("stop"))
    if isinstance(stop_value, str):
        stop_sequences = [stop_value]
    elif isinstance(stop_value, list):
        stop_sequences = [value for value in stop_value if isinstance(value, str)]
    else:
        stop_sequences = []

    max_tokens = data.get("max_output_tokens")
    if not isinstance(max_tokens, int) or isinstance(max_tokens, bool):
        max_tokens = 0

    temperature = data.get("temperature")
    top_p = data.get("top_p")
    top_k = data.get("top_k")

    return SamplingParams(
        max_tokens=max_tokens,
        temperature=temperature if isinstance(temperature, int | float) else None,
        top_p=top_p if isinstance(top_p, int | float) else None,
        top_k=top_k if isinstance(top_k, int) and not isinstance(top_k, bool) else None,
        stop_sequences=stop_sequences,
    )
