"""Shared builders for override tests."""

from __future__ import annotations

from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
    ToolDef,
)


def make_ir(
    system: list[SystemPart] | None = None,
    tools: list[ToolDef] | None = None,
    messages: list[Message] | None = None,
) -> InternalRequest:
    return InternalRequest(
        model="claude-3",
        provider="anthropic",
        system=system or [],
        tools=tools or [],
        messages=messages or [Message(role="user", content=[TextBlock(text="hello")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


TOOL_BASH = ToolDef(
    name="mcp_bash",
    description="Execute shell commands",
    input_schema={"type": "object", "properties": {"cmd": {"type": "string"}}},
)

TOOL_READ = ToolDef(
    name="Read",
    description="Read a file from disk",
    input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
)
