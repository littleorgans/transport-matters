"""Private audit models and char accounting helpers for overrides."""

from typing import Any  # Any: opaque provider blobs

from pydantic import BaseModel, ConfigDict

from transport_matters.canonicalization import canonical_fields, canonical_json, json_string
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


def _provider_data(value: dict[str, Any] | None) -> str:
    return "null" if value is None else canonical_json(value)


def canonical_block_json(block: ContentBlock) -> str:
    """Return canonical field-ordered JSON for one IR content block."""
    if isinstance(block, TextBlock):
        return canonical_fields(
            [
                ("type", json_string(block.type)),
                ("text", json_string(block.text)),
                ("provider_data", _provider_data(block.provider_data)),
            ]
        )
    if isinstance(block, ToolUseBlock):
        return canonical_fields(
            [
                ("type", json_string(block.type)),
                ("id", json_string(block.id)),
                ("name", json_string(block.name)),
                ("input", canonical_json(block.input)),
                ("provider_data", _provider_data(block.provider_data)),
            ]
        )
    if isinstance(block, ToolResultBlock):
        content = "[" + ",".join(canonical_block_json(item) for item in block.content) + "]"
        return canonical_fields(
            [
                ("type", json_string(block.type)),
                ("tool_use_id", json_string(block.tool_use_id)),
                ("content", content),
                ("is_error", canonical_json(block.is_error)),
                ("provider_data", _provider_data(block.provider_data)),
            ]
        )
    if isinstance(block, ThinkingBlock):
        return canonical_fields(
            [
                ("type", json_string(block.type)),
                ("text", json_string(block.text)),
                ("provider_data", _provider_data(block.provider_data)),
            ]
        )
    if isinstance(block, ImageBlock):
        return canonical_fields(
            [
                ("type", json_string(block.type)),
                ("source", canonical_json(block.source)),
                ("provider_data", _provider_data(block.provider_data)),
            ]
        )
    if isinstance(block, UnknownBlock):
        return canonical_fields(
            [
                ("type", json_string(block.type)),
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
