from __future__ import annotations

from typing import TYPE_CHECKING

from manicure.ir import (
    InternalRequest,
    InternalResponse,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
    UsageStats,
)

if TYPE_CHECKING:
    from manicure.track_manager import TrackAssignment, TrackManager

ROOT_RUN_ID = "run-root"
CLAUDE_SPAWN_ID = "toolu_01MiLL7GyXKvFTneZmojAazu"
CODEX_SPAWN_ID = "call_Qp6Z4Fq3ZMJG9TIQJxEoueHB"
CODEX_AGENT_ID = "019dc432-c4bc-75d2-a8e5-be095061139d"


def _tool(name: str) -> ToolDef:
    return ToolDef(name=name, description=name, input_schema={})


def _request(
    *,
    provider: str = "anthropic",
    tools_count: int = 3,
    messages: list[Message] | None = None,
    provider_metadata: dict[str, object] | None = None,
) -> InternalRequest:
    return InternalRequest(
        model="model",
        provider=provider,
        system=[],
        tools=[_tool(f"tool_{index}") for index in range(tools_count)],
        messages=messages or [Message(role="user", content=[TextBlock(text="hi")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(provider_metadata=provider_metadata or {}),
    )


def _response(
    *,
    provider: str = "anthropic",
    content: list[TextBlock | ToolUseBlock] | None = None,
) -> InternalResponse:
    return InternalResponse(
        id="resp",
        model="model",
        provider=provider,
        usage=UsageStats(),
        content=content or [TextBlock(text="ok")],
    )


def _tool_result(tool_use_id: str, text: str) -> ToolResultBlock:
    return ToolResultBlock(
        tool_use_id=tool_use_id,
        content=[TextBlock(text=text)],
    )


def _run_trace(
    manager: TrackManager,
    run_id: str,
    trace: list[tuple[str, InternalRequest, InternalResponse | None]],
) -> dict[str, TrackAssignment]:
    assignments: dict[str, TrackAssignment] = {}
    for exchange_id, request, response in trace:
        assignments[exchange_id] = manager.record_exchange(
            run_id, request, response, exchange_id=exchange_id
        )
    return assignments
