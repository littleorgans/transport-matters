"""Tests for decomposed addon phase helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from manicure import broadcast

if TYPE_CHECKING:
    import pytest
from manicure.addon import (
    _build_pipeline_stats,
    _build_req_stats,
    _emit_exchange,
    _parse_sse_stats,
    _resolve_paused_flow,
)
from manicure.breakpoint import PausedFlow
from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
    ToolDef,
)
from manicure.overrides import OverrideAudit, OverrideAuditEntry
from manicure.storage.base import PipelineStats


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


def test_build_req_stats_counts_content_blocks_not_messages() -> None:
    """messages_count should reflect total content blocks, not message objects."""
    ir = InternalRequest(
        model="claude-3",
        provider="anthropic",
        system=[],
        tools=[],
        messages=[
            Message(role="user", content=[]),
            Message(
                role="user",
                content=[TextBlock(text="a"), TextBlock(text="b"), TextBlock(text="c")],
            ),
        ],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )
    stats = _build_req_stats(ir)
    assert stats.messages_count == 3  # 0 + 3 blocks, not 2 messages


def test_build_req_stats_empty_content_yields_zero() -> None:
    """A single message with empty content should count as 0."""
    ir = InternalRequest(
        model="claude-3",
        provider="anthropic",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )
    stats = _build_req_stats(ir)
    assert stats.messages_count == 0


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
    audit = OverrideAudit(
        entries=[
            OverrideAuditEntry(
                kind="tool_toggle",
                target="tool:mcp_bash",
                applied=True,
                chars_delta=-200,
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
    assert len(stats.overrides_applied) == 1
    assert stats.overrides_applied[0].kind == "tool_toggle"


def test_build_pipeline_stats_empty_overrides() -> None:
    audit = OverrideAudit(entries=[], chars_before=500, chars_after=500)
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


def test_parse_sse_stats_warns_on_invalid_utf8(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Invalid UTF-8 bytes should trigger a warning and fall back to replacement."""
    import logging

    # 0xff 0xfe are invalid UTF-8 byte sequences
    raw = b"data: \xff\xfe invalid bytes\n"
    with caplog.at_level(logging.WARNING, logger="manicure.addon"):
        stats = _parse_sse_stats(raw)
    assert "invalid UTF-8" in caplog.text
    # Should still return stats (best-effort parsing)
    assert stats.input_tokens == 0


# ── _emit_exchange ─────────────────────────────────────────────────


class TestEmitExchange:
    """_emit_exchange SSE payload includes mutated_manually and pipeline fields."""

    def setup_method(self) -> None:
        broadcast._subscribers.clear()
        broadcast._next_id = 0

    def teardown_method(self) -> None:
        broadcast._subscribers.clear()
        broadcast._next_id = 0

    def test_payload_includes_mutated_manually_and_pipeline(self) -> None:
        import json
        from datetime import UTC, datetime

        ir = _make_ir()
        req_stats = _build_req_stats(ir)
        pipeline_stats = PipelineStats(
            overrides_applied=[],
            chars_before=100,
            chars_after=80,
            tokens_approx=60,
        )
        q = broadcast.subscribe()

        _emit_exchange(
            ir,
            req_stats,
            None,
            "exchange-1",
            datetime(2026, 1, 1, tzinfo=UTC),
            mutated_manually=True,
            pipeline_stats=pipeline_stats,
        )

        assert not q.empty()
        data = json.loads(q.get_nowait())
        assert data["mutated_manually"] is True
        assert data["pipeline"]["chars_before"] == 100
        assert data["pipeline"]["chars_after"] == 80

    def test_payload_includes_flow_id_when_provided(self) -> None:
        import json
        from datetime import UTC, datetime

        ir = _make_ir()
        req_stats = _build_req_stats(ir)
        q = broadcast.subscribe()

        _emit_exchange(
            ir,
            req_stats,
            None,
            "exchange-3",
            datetime(2026, 1, 1, tzinfo=UTC),
            flow_id="mitmproxy-flow-abc123",
        )

        data = json.loads(q.get_nowait())
        assert data["flow_id"] == "mitmproxy-flow-abc123"

    def test_payload_omits_flow_id_when_none(self) -> None:
        import json
        from datetime import UTC, datetime

        ir = _make_ir()
        req_stats = _build_req_stats(ir)
        q = broadcast.subscribe()

        _emit_exchange(
            ir,
            req_stats,
            None,
            "exchange-4",
            datetime(2026, 1, 1, tzinfo=UTC),
        )

        data = json.loads(q.get_nowait())
        assert "flow_id" not in data

    def test_defaults_omit_pipeline_and_mutated_false(self) -> None:
        import json
        from datetime import UTC, datetime

        ir = _make_ir()
        req_stats = _build_req_stats(ir)
        q = broadcast.subscribe()

        _emit_exchange(
            ir, req_stats, None, "exchange-2", datetime(2026, 1, 1, tzinfo=UTC)
        )

        assert not q.empty()
        data = json.loads(q.get_nowait())
        assert data["mutated_manually"] is False
        assert data["pipeline"] is None


# ── _resolve_paused_flow ───────────────────────────────────────────


class TestResolvePausedFlow:
    """Determines (final_ir, mutated_manually) from a released paused flow.

    Clicking Forward through the editor populates ``pf.mutated_ir`` even when
    the user did not actually change anything. The helper must treat that
    no-op submission the same as a Pass Through release.
    """

    def _paused(
        self,
        curated_ir: InternalRequest,
        mutated_ir: InternalRequest | None,
    ) -> PausedFlow:
        import asyncio

        # The flow object is never read by _resolve_paused_flow, but PausedFlow
        # requires the attribute. None is fine for this pure-logic test.
        return PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=asyncio.Event(),
            original_ir=curated_ir,
            curated_ir=curated_ir,
            paused_at_ms=0,
            mutated_ir=mutated_ir,
        )

    def test_pass_through_reports_no_mutation(self) -> None:
        """mutated_ir=None (Pass Through button) forwards curated_ir, flag False."""
        curated = _make_ir(message_text="hello")
        final_ir, mutated = _resolve_paused_flow(self._paused(curated, None))
        assert final_ir is curated
        assert mutated is False

    def test_forward_unchanged_reports_no_mutation(self) -> None:
        """Forward-clicked with IR equal to curated must not mark as mutated.

        Regression guard: the editor pre-fills with curated_ir, so a user
        who opens and immediately submits should produce no "Edited" badge.
        """
        curated = _make_ir(message_text="hello")
        unchanged = _make_ir(message_text="hello")
        assert curated == unchanged  # Pydantic v2 structural equality
        final_ir, mutated = _resolve_paused_flow(self._paused(curated, unchanged))
        assert final_ir is unchanged
        assert mutated is False

    def test_forward_with_edits_reports_mutation(self) -> None:
        """A genuine edit produces mutated=True."""
        curated = _make_ir(message_text="hello")
        edited = _make_ir(message_text="hello world")
        assert curated != edited
        final_ir, mutated = _resolve_paused_flow(self._paused(curated, edited))
        assert final_ir is edited
        assert mutated is True
