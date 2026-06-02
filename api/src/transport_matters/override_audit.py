"""Private audit models and char accounting helpers for overrides."""

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from transport_matters.ir import (
    ContentBlock,
    ImageBlock,
    InternalRequest,
    TextBlock,
    ThinkingBlock,
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
)


class OverrideAuditEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    target: str
    applied: bool
    chars_delta: int
    curated_value: str | None = None


class OverrideAudit(BaseModel):
    entries: list[OverrideAuditEntry]
    chars_before: int
    chars_after: int
    system_chars_before: int = 0
    system_chars_after: int = 0
    tools_chars_before: int = 0
    tools_chars_after: int = 0
    messages_chars_before: int = 0
    messages_chars_after: int = 0

    @property
    def chars_delta(self) -> int:
        return self.chars_after - self.chars_before


_EXPONENT_RE = re.compile(r"e([+-]?)(0*)(\d+)$")
_MAX_DECIMAL_INTEGER_FLOAT = 1e21


def _json_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _canonical_exponent(value: str) -> str:
    return _EXPONENT_RE.sub(
        lambda match: f"e{'-' if match.group(1) == '-' else ''}{int(match.group(3))}",
        value.lower(),
    )


def _canonical_number(value: int | float) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise ValueError("non-finite numbers are not valid char-accounting JSON")
    if value.is_integer() and abs(value) < _MAX_DECIMAL_INTEGER_FLOAT:
        return str(int(value))
    # TypeScript mirrors Python's exponent threshold for small decimal floats.
    return _canonical_exponent(
        json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    )


def _canonical_mapping(value: Mapping[str, Any]) -> str:
    fields = []
    for key in value:
        if not isinstance(key, str):
            raise ValueError("char-accounting JSON object keys must be strings")
    for key in sorted(value):
        fields.append(f"{_json_string(key)}:{canonical_json(value[key])}")
    return "{" + ",".join(fields) + "}"


def canonical_json(value: Any) -> str:
    """Return canonical compact JSON for embedded IR dictionaries."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return _json_string(value)
    if isinstance(value, int | float):
        return _canonical_number(value)
    if isinstance(value, Mapping):
        return _canonical_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    raise TypeError(f"Unsupported char-accounting JSON value: {type(value).__name__}")


def _canonical_fields(fields: Sequence[tuple[str, str]]) -> str:
    return "{" + ",".join(f"{_json_string(key)}:{value}" for key, value in fields) + "}"


def _provider_data(value: dict[str, Any] | None) -> str:
    return "null" if value is None else canonical_json(value)


def canonical_block_json(block: ContentBlock) -> str:
    """Return canonical field-ordered JSON for one IR content block."""
    if isinstance(block, TextBlock):
        return _canonical_fields(
            [
                ("type", _json_string(block.type)),
                ("text", _json_string(block.text)),
                ("provider_data", _provider_data(block.provider_data)),
            ]
        )
    if isinstance(block, ToolUseBlock):
        return _canonical_fields(
            [
                ("type", _json_string(block.type)),
                ("id", _json_string(block.id)),
                ("name", _json_string(block.name)),
                ("input", canonical_json(block.input)),
                ("provider_data", _provider_data(block.provider_data)),
            ]
        )
    if isinstance(block, ToolResultBlock):
        content = "[" + ",".join(canonical_block_json(item) for item in block.content) + "]"
        return _canonical_fields(
            [
                ("type", _json_string(block.type)),
                ("tool_use_id", _json_string(block.tool_use_id)),
                ("content", content),
                ("is_error", canonical_json(block.is_error)),
                ("provider_data", _provider_data(block.provider_data)),
            ]
        )
    if isinstance(block, ThinkingBlock):
        return _canonical_fields(
            [
                ("type", _json_string(block.type)),
                ("text", _json_string(block.text)),
                ("provider_data", _provider_data(block.provider_data)),
            ]
        )
    if isinstance(block, ImageBlock):
        return _canonical_fields(
            [
                ("type", _json_string(block.type)),
                ("source", canonical_json(block.source)),
                ("provider_data", _provider_data(block.provider_data)),
            ]
        )
    if isinstance(block, UnknownBlock):
        return _canonical_fields(
            [
                ("type", _json_string(block.type)),
                ("raw", canonical_json(block.raw)),
            ]
        )
    raise TypeError(f"Unsupported content block: {type(block).__name__}")


def block_chars(block: ContentBlock) -> int:
    return len(canonical_block_json(block))


def tool_chars(tool: ToolDef) -> int:
    return len(tool.name) + len(tool.description) + len(canonical_json(tool.input_schema))


def count_chars_parts(ir: InternalRequest) -> tuple[int, int, int]:
    """Return (system_chars, tools_chars, messages_chars) for an IR."""
    system_chars = sum(len(part.text) for part in ir.system)
    tools_chars = sum(tool_chars(tool) for tool in ir.tools)
    messages_chars = 0
    for message in ir.messages:
        for block in message.content:
            messages_chars += block_chars(block)
    return system_chars, tools_chars, messages_chars


def identity_audit(ir: InternalRequest) -> OverrideAudit:
    """Return a zero-delta audit with no entries."""
    system_chars, tools_chars, messages_chars = count_chars_parts(ir)
    total = system_chars + tools_chars + messages_chars
    return OverrideAudit(
        entries=[],
        chars_before=total,
        chars_after=total,
        system_chars_before=system_chars,
        system_chars_after=system_chars,
        tools_chars_before=tools_chars,
        tools_chars_after=tools_chars,
        messages_chars_before=messages_chars,
        messages_chars_after=messages_chars,
    )
