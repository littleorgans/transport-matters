"""Shared request and response exchange helpers."""

from __future__ import annotations

import json
import logging
from typing import Any

from transport_matters.counting import TokenCountingClient, count_before_after
from transport_matters.ir import (
    ContentBlock,
    InternalRequest,
    InternalResponse,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from transport_matters.overrides import OverrideAudit, count_chars_parts
from transport_matters.request_diff import request_unchanged
from transport_matters.storage import PipelineStats, ReqStats, ResStats

logger = logging.getLogger(__name__)


def extract_user_prompt_text(ir: InternalRequest) -> str | None:
    """Full text from the last user message for lazy per-card rendering."""
    for message in reversed(ir.messages):
        if message.role != "user":
            continue
        text = _flatten_user_text(message.content)
        stripped = text.strip()
        return stripped or None
    return None


def _flatten_user_text(blocks: list[ContentBlock]) -> str:
    """Pick preview text from the most recent renderable block in a user message.

    TextBlock wins on its own text. ToolResultBlock falls back to joined inner
    TextBlock text. Image, ToolUse, Thinking, Unknown blocks are skipped.
    """
    for block in reversed(blocks):
        if isinstance(block, TextBlock):
            if block.text:
                return block.text
        elif isinstance(block, ToolResultBlock):
            parts = [
                inner.text
                for inner in block.content
                if isinstance(inner, TextBlock) and inner.text
            ]
            if parts:
                return "\n".join(parts)
    return ""


def extract_response_text(res: InternalResponse) -> str | None:
    """Full assistant text for lazy per-card rendering."""
    text_parts: list[str] = []
    tool_use_input: str | None = None
    thinking_text: str | None = None
    for block in res.content:
        if isinstance(block, TextBlock):
            if block.text:
                text_parts.append(block.text)
        elif isinstance(block, ToolUseBlock):
            if tool_use_input is None:
                tool_use_input = json.dumps(block.input)
        elif isinstance(block, ThinkingBlock) and thinking_text is None and block.text:
            thinking_text = f"<thinking>{block.text}</thinking>"
    if text_parts:
        return "\n".join(text_parts)
    if tool_use_input is not None:
        return tool_use_input
    return thinking_text


def build_req_stats(ir: InternalRequest) -> ReqStats:
    """Build request stats from an InternalRequest."""
    system_chars, tools_chars, messages_chars = count_chars_parts(ir)
    return ReqStats(
        system_parts=len(ir.system),
        system_chars=system_chars,
        tools_count=len(ir.tools),
        tools_chars=tools_chars,
        messages_count=sum(len(m.content) for m in ir.messages),
        messages_chars=messages_chars,
        total_chars=system_chars + tools_chars + messages_chars,
    )


def build_res_stats(res_ir: InternalResponse) -> ResStats:
    """Derive the index row's response stats from a parsed IR."""
    text_chars = 0
    tool_calls = 0
    for block in res_ir.content:
        if isinstance(block, TextBlock):
            text_chars += len(block.text)
        elif isinstance(block, ToolUseBlock):
            tool_calls += 1

    return ResStats(
        stop_reason=res_ir.stop_reason,
        input_tokens=res_ir.usage.input_tokens,
        output_tokens=res_ir.usage.output_tokens,
        cache_creation_input_tokens=res_ir.usage.cache_creation_input_tokens,
        cache_read_input_tokens=res_ir.usage.cache_read_input_tokens,
        text_chars=text_chars,
        tool_calls=tool_calls,
    )


def _parse_response_ir(
    adapter: Any,  # Any: adapter protocol has no shared base
    raw_res: bytes,
    content_type: str,
    exchange_id: str,
) -> tuple[InternalResponse | None, ResStats | None]:
    """Parse raw response bytes to IR and stats. Returns (None, None) on failure."""
    if not raw_res:
        return None, None
    try:
        res_ir = adapter.inbound_response(raw_res, content_type)
        res_stats = build_res_stats(res_ir)
        return res_ir, res_stats
    except Exception:
        logger.exception("Failed to parse response for flow %s", exchange_id)
        return None, None


def build_pipeline_stats(audit: OverrideAudit | None) -> PipelineStats | None:
    """Convert an OverrideAudit to the storable PipelineStats."""
    if audit is None:
        return None
    return PipelineStats(
        overrides_applied=list(audit.entries),
        chars_before=audit.chars_before,
        chars_after=audit.chars_after,
    )


async def stamp_pipeline_tokens(
    stats: PipelineStats,
    original_ir: InternalRequest,
    curated_ir: InternalRequest,
    adapter: Any,  # Any: adapter protocol has no shared base
    counter: TokenCountingClient,
    auth_headers: dict[str, str],
) -> PipelineStats:
    """Attach before and after token counts from /v1/messages/count_tokens."""
    # When the pipeline changed nothing, the after-count equals the before-count.
    # Pass None so count_before_after collapses to a single call and the curated
    # IR is never reserialized.
    after_payload = (
        None
        if request_unchanged(original_ir, curated_ir)
        else adapter.outbound_request(curated_ir)
    )
    tokens_before, tokens_after = await count_before_after(
        counter,
        auth_headers,
        adapter.outbound_request(original_ir),
        after_payload,
    )
    if tokens_before is None or tokens_after is None:
        return stats
    return stats.model_copy(
        update={"tokens_before": tokens_before, "tokens_after": tokens_after}
    )
