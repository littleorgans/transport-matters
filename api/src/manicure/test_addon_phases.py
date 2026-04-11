"""Tests for decomposed addon phase helpers."""

from __future__ import annotations

from manicure.addon import (
    _build_pipeline_stats,
    _build_req_stats,
    _parse_sse_stats,
)
from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
    ToolDef,
)
from manicure.pipeline import PipelineAudit
from manicure.storage.base import RuleAuditEntry


def _make_ir(
    system_text: str = "",
    tools: list[ToolDef] | None = None,
    message_text: str = "hello",
) -> InternalRequest:
    return InternalRequest(
        model="claude-3",
        provider="anthropic",
        system=[SystemPart(text=system_text)] if system_text else [],
        tools=tools or [],
        messages=[Message(role="user", content=[TextBlock(text=message_text)])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


# ── _build_req_stats ────────────────────────────────────────────────


def test_build_req_stats_empty_ir() -> None:
    ir = _make_ir()
    stats = _build_req_stats(ir)
    assert stats.system_parts == 0
    assert stats.system_chars == 0
    assert stats.tools_count == 0
    assert stats.messages_count == 1
    assert stats.messages_chars > 0
    assert stats.total_chars == stats.messages_chars


def test_build_req_stats_with_system() -> None:
    ir = _make_ir(system_text="You are a helpful assistant.")
    stats = _build_req_stats(ir)
    assert stats.system_parts == 1
    assert stats.system_chars == len("You are a helpful assistant.")


def test_build_req_stats_with_tools() -> None:
    tools = [
        ToolDef(
            name="search", description="Search the web", input_schema={"type": "object"}
        )
    ]
    ir = _make_ir(tools=tools)
    stats = _build_req_stats(ir)
    assert stats.tools_count == 1
    assert stats.tools_chars > 0


def test_build_req_stats_total_is_sum_of_parts() -> None:
    tools = [ToolDef(name="fn", description="desc", input_schema={"type": "object"})]
    ir = _make_ir(system_text="sys", tools=tools, message_text="msg")
    stats = _build_req_stats(ir)
    assert (
        stats.total_chars
        == stats.system_chars + stats.tools_chars + stats.messages_chars
    )


# ── _build_pipeline_stats ───────────────────────────────────────────


def test_build_pipeline_stats_none_returns_none() -> None:
    assert _build_pipeline_stats(None) is None


def test_build_pipeline_stats_converts_audit() -> None:
    audit = PipelineAudit(
        rules_applied=[
            RuleAuditEntry(
                id="r1", name="strip", action="strip_tools", removed={"tools": 3}
            )
        ],
        chars_before=1000,
        chars_after=800,
    )
    stats = _build_pipeline_stats(audit)
    assert stats is not None
    assert stats.chars_before == 1000
    assert stats.chars_after == 800
    assert stats.tokens_approx == 50  # |200| // 4
    assert len(stats.rules_applied) == 1
    assert stats.rules_applied[0].id == "r1"


def test_build_pipeline_stats_empty_rules() -> None:
    audit = PipelineAudit(rules_applied=[], chars_before=500, chars_after=500)
    stats = _build_pipeline_stats(audit)
    assert stats is not None
    assert stats.tokens_approx == 0


# ── _parse_sse_stats ────────────────────────────────────────────────


def test_parse_sse_stats_empty_bytes() -> None:
    stats = _parse_sse_stats(b"")
    assert stats.input_tokens == 0
    assert stats.output_tokens == 0
    assert stats.stop_reason is None


def test_parse_sse_stats_message_start_and_delta() -> None:
    raw = (
        b'data: {"type": "message_start", "message": {"usage": {"input_tokens": 42, "cache_read_input_tokens": 5}}}\n'
        b'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 17}}\n'
    )
    stats = _parse_sse_stats(raw)
    assert stats.input_tokens == 42
    assert stats.cache_read_input_tokens == 5
    assert stats.output_tokens == 17
    assert stats.stop_reason == "end_turn"


def test_parse_sse_stats_text_chars() -> None:
    raw = b'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello!"}}\n'
    stats = _parse_sse_stats(raw)
    assert stats.text_chars == 6


def test_parse_sse_stats_tool_use_count() -> None:
    raw = (
        b'data: {"type": "content_block_start", "content_block": {"type": "tool_use", "id": "t1", "name": "fn"}}\n'
        b'data: {"type": "content_block_start", "content_block": {"type": "tool_use", "id": "t2", "name": "gn"}}\n'
    )
    stats = _parse_sse_stats(raw)
    assert stats.tool_calls == 2


def test_parse_sse_stats_ignores_malformed_lines() -> None:
    raw = b"data: not-json\ndata: [DONE]\n"
    stats = _parse_sse_stats(raw)
    assert stats.input_tokens == 0
