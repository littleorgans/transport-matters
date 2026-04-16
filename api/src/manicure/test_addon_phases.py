"""Tests for decomposed addon phase helpers."""

from __future__ import annotations

import asyncio

from manicure import breakpoint as bp
from manicure import broadcast
from manicure.adapters.anthropic import AnthropicAdapter
from manicure.addon import (
    _build_pipeline_stats,
    _build_req_stats,
    _build_res_stats,
    _emit_exchange,
    _fire_pause_count,
    _resolve_paused_flow,
    _stamp_pipeline_tokens,
)
from manicure.breakpoint import PausedFlow
from manicure.ir import (
    InternalRequest,
    InternalResponse,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
    ToolDef,
    ToolUseBlock,
    UsageStats,
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
    # Token counts start unset; _stamp_pipeline_tokens fills them later.
    assert stats.tokens_before is None
    assert stats.tokens_after is None
    assert len(stats.overrides_applied) == 1
    assert stats.overrides_applied[0].kind == "tool_toggle"


def test_build_pipeline_stats_empty_overrides() -> None:
    audit = OverrideAudit(entries=[], chars_before=500, chars_after=500)
    stats = _build_pipeline_stats(audit)
    assert stats is not None
    assert stats.tokens_before is None
    assert stats.tokens_after is None


# ── _stamp_pipeline_tokens ──────────────────────────────────────────


class _SeqCounter:
    """Deterministic TokenCountingClient that yields values in order.

    Structurally satisfies the Protocol in manicure.counting. Each call
    appends the posted payload to ``payloads`` and returns the next
    pre-seeded value.
    """

    def __init__(self, values: list[int | None]) -> None:
        self._iter = iter(values)
        self.payloads: list[bytes] = []
        self.calls = 0

    async def count(self, payload: bytes, auth_headers: dict[str, str]) -> int | None:
        self.calls += 1
        self.payloads.append(payload)
        return next(self._iter)


class TestStampPipelineTokens:
    """_stamp_pipeline_tokens attaches token counts from the counter.

    Payload equality is the fast path — no structural change means the
    before and after wires are identical, so one lookup fills both fields.
    """

    async def test_distinct_payloads_make_two_calls(self) -> None:
        stats = PipelineStats(overrides_applied=[], chars_before=100, chars_after=80)
        original = _make_ir(message_text="hello world")
        curated = _make_ir(message_text="hi")
        counter = _SeqCounter([50, 30])

        stamped = await _stamp_pipeline_tokens(
            stats, original, curated, AnthropicAdapter(), counter, {"x-api-key": "k"}
        )

        assert stamped.tokens_before == 50
        assert stamped.tokens_after == 30
        assert counter.calls == 2

    async def test_identical_payloads_make_one_call(self) -> None:
        """No-op pipeline reuses the single count for both fields."""
        stats = PipelineStats(overrides_applied=[], chars_before=100, chars_after=100)
        ir = _make_ir()
        counter = _SeqCounter([42])

        stamped = await _stamp_pipeline_tokens(
            stats, ir, ir, AnthropicAdapter(), counter, {}
        )

        assert stamped.tokens_before == 42
        assert stamped.tokens_after == 42
        assert counter.calls == 1

    async def test_counter_failure_leaves_stats_untouched(self) -> None:
        """Full failure: stats stays as it was (both tokens remain None).

        Persisting None-None would be harmless on its own, but going
        through the stamp path for a partial (42, None) result and
        writing that back to the index would freeze the null side behind
        the lazy-recount endpoint's "already stamped" short-circuit.
        The simplest rule that covers both cases: if any side is None,
        return stats unchanged.
        """
        stats = PipelineStats(overrides_applied=[], chars_before=100, chars_after=80)
        original = _make_ir(message_text="x")
        curated = _make_ir(message_text="y")
        counter = _SeqCounter([None, None])

        stamped = await _stamp_pipeline_tokens(
            stats, original, curated, AnthropicAdapter(), counter, {}
        )

        assert stamped.tokens_before is None
        assert stamped.tokens_after is None

    async def test_partial_before_only_leaves_stats_untouched(self) -> None:
        """(42, None) is treated as a failure: no sticky partial stamp."""
        stats = PipelineStats(overrides_applied=[], chars_before=100, chars_after=80)
        original = _make_ir(message_text="x")
        curated = _make_ir(message_text="y")
        counter = _SeqCounter([42, None])

        stamped = await _stamp_pipeline_tokens(
            stats, original, curated, AnthropicAdapter(), counter, {}
        )

        assert stamped.tokens_before is None
        assert stamped.tokens_after is None

    async def test_partial_after_only_leaves_stats_untouched(self) -> None:
        """(None, 42) mirrors the (42, None) path — partial still fails closed."""
        stats = PipelineStats(overrides_applied=[], chars_before=100, chars_after=80)
        original = _make_ir(message_text="x")
        curated = _make_ir(message_text="y")
        counter = _SeqCounter([None, 42])

        stamped = await _stamp_pipeline_tokens(
            stats, original, curated, AnthropicAdapter(), counter, {}
        )

        assert stamped.tokens_before is None
        assert stamped.tokens_after is None

    async def test_identical_payloads_single_none_leaves_stats_untouched(self) -> None:
        """Single-call path returns None: stats stays untouched, same rule."""
        stats = PipelineStats(overrides_applied=[], chars_before=100, chars_after=100)
        ir = _make_ir()
        counter = _SeqCounter([None])

        stamped = await _stamp_pipeline_tokens(
            stats, ir, ir, AnthropicAdapter(), counter, {}
        )

        assert stamped.tokens_before is None
        assert stamped.tokens_after is None
        assert counter.calls == 1

    async def test_preserves_chars_and_overrides(self) -> None:
        """Stamping only touches token fields; everything else is immutable."""
        entry = OverrideAuditEntry(
            kind="tool_toggle", target="t:x", applied=True, chars_delta=-10
        )
        stats = PipelineStats(
            overrides_applied=[entry], chars_before=500, chars_after=490
        )
        ir = _make_ir()
        counter = _SeqCounter([99])

        stamped = await _stamp_pipeline_tokens(
            stats, ir, ir, AnthropicAdapter(), counter, {}
        )

        assert stamped.chars_before == 500
        assert stamped.chars_after == 490
        assert stamped.overrides_applied == [entry]


# ── _build_res_stats ────────────────────────────────────────────────


def _make_response_ir(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    stop_reason: str | None = None,
    content: list[TextBlock | ToolUseBlock] | None = None,
) -> InternalResponse:
    return InternalResponse(
        id="msg_test",
        model="anthropic/claude-sonnet-4-5",
        provider="anthropic",
        stop_reason=stop_reason,
        usage=UsageStats(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        ),
        content=list(content or []),
    )


def test_build_res_stats_forwards_all_usage_fields() -> None:
    """The four Anthropic usage fields must survive the IR → ResStats hop.

    Regression guard for cache_creation_input_tokens, which used to be
    dropped between UsageStats and ResStats.
    """
    res_ir = _make_response_ir(
        input_tokens=42,
        output_tokens=17,
        cache_creation_input_tokens=128,
        cache_read_input_tokens=5,
        stop_reason="end_turn",
    )
    stats = _build_res_stats(res_ir)
    assert stats.input_tokens == 42
    assert stats.output_tokens == 17
    assert stats.cache_creation_input_tokens == 128
    assert stats.cache_read_input_tokens == 5
    assert stats.stop_reason == "end_turn"


def test_build_res_stats_counts_text_and_tool_blocks() -> None:
    res_ir = _make_response_ir(
        content=[
            TextBlock(text="Hello!"),
            ToolUseBlock(id="t1", name="fn", input={}),
            ToolUseBlock(id="t2", name="gn", input={}),
        ],
    )
    stats = _build_res_stats(res_ir)
    assert stats.text_chars == 6
    assert stats.tool_calls == 2


def test_build_res_stats_empty_content_is_zero() -> None:
    stats = _build_res_stats(_make_response_ir())
    assert stats.text_chars == 0
    assert stats.tool_calls == 0


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
            tokens_before=60,
            tokens_after=50,
        )
        q = broadcast.subscribe()

        _emit_exchange(
            ir,
            req_stats,
            None,
            "exchange-1",
            datetime(2026, 1, 1, tzinfo=UTC),
            None,
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
            None,
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
            None,
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
            ir, req_stats, None, "exchange-2", datetime(2026, 1, 1, tzinfo=UTC), None
        )

        assert not q.empty()
        data = json.loads(q.get_nowait())
        assert data["mutated_manually"] is False
        assert data["pipeline"] is None


# ── _fire_pause_count ──────────────────────────────────────────────


class TestFirePauseCount:
    """Background helper that counts tokens and emits a follow-up event.

    Runs after the initial ``paused`` broadcast so the UI renders fast;
    should only emit when the count is real AND the flow is still paused.
    """

    def setup_method(self) -> None:
        broadcast._subscribers.clear()
        broadcast._next_id = 0
        bp._paused.clear()

    def teardown_method(self) -> None:
        broadcast._subscribers.clear()
        broadcast._next_id = 0
        bp._paused.clear()

    async def _register(self, flow_id: str) -> bp.PausedFlow:
        ir = _make_ir()
        event = asyncio.Event()
        pf = bp.PausedFlow(
            flow=None,  # type: ignore[arg-type]
            event=event,
            original_ir=ir,
            curated_ir=ir,
            paused_at_ms=0,
        )
        bp._paused[flow_id] = pf
        return pf

    async def test_success_stores_and_broadcasts(self) -> None:
        import json

        pf = await self._register("flow-A")
        q = broadcast.subscribe()
        counter = _SeqCounter([42])

        await _fire_pause_count("flow-A", counter, b'{"model":"x"}', {"k": "v"})

        assert pf.tokens_before == 42
        data = json.loads(q.get_nowait())
        assert data["type"] == "paused_tokens"
        assert data["flow_id"] == "flow-A"
        assert data["tokens_before"] == 42
        assert counter.calls == 1

    async def test_counter_none_does_not_broadcast(self) -> None:
        """A None counter result keeps the em dash; no follow-up event."""
        pf = await self._register("flow-B")
        q = broadcast.subscribe()
        counter = _SeqCounter([None])

        await _fire_pause_count("flow-B", counter, b"{}", {})

        assert pf.tokens_before is None
        assert q.empty()

    async def test_flow_already_released_does_not_broadcast(self) -> None:
        """Race: counter finishes after user released the flow — silent drop."""
        q = broadcast.subscribe()
        counter = _SeqCounter([99])

        # Flow never registered: set_tokens_before returns False.
        await _fire_pause_count("flow-GONE", counter, b"{}", {})

        assert q.empty()

    async def test_counter_exception_silently_swallowed(self) -> None:
        """Counter raising must not bubble up to cancel the pause."""

        class _Boom:
            async def count(
                self, payload: bytes, auth_headers: dict[str, str]
            ) -> int | None:
                raise RuntimeError("boom")

        pf = await self._register("flow-E")
        q = broadcast.subscribe()

        await _fire_pause_count("flow-E", _Boom(), b"{}", {})

        assert pf.tokens_before is None
        assert q.empty()


# ── _resolve_paused_flow ───────────────────────────────────────────


class TestResolvePausedFlow:
    """Determines (final_ir, mutated_manually, audit) from a released paused flow.

    Clicking Forward through the editor populates ``pf.mutated_ir`` even when
    the user did not actually change anything. The helper must treat that
    no-op submission the same as a Pass Through release.

    The returned audit is the paused flow's live ``pf.audit`` (possibly
    refreshed by ``_update_paused_preview`` mid-pause) whenever the user
    forwarded the pipeline's curated IR; it must be None whenever the user
    manually edited the textareas, because ``pf.audit`` describes
    ``pf.curated_ir`` — not the ``pf.mutated_ir`` that actually shipped.
    """

    def _paused(
        self,
        curated_ir: InternalRequest,
        mutated_ir: InternalRequest | None,
        audit: OverrideAudit | None = None,
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
            audit=audit,
        )

    def test_pass_through_reports_no_mutation(self) -> None:
        """mutated_ir=None (Pass Through button) forwards curated_ir, flag False."""
        curated = _make_ir(message_text="hello")
        final_ir, mutated, audit = _resolve_paused_flow(self._paused(curated, None))
        assert final_ir is curated
        assert mutated is False
        assert audit is None

    def test_forward_unchanged_reports_no_mutation(self) -> None:
        """Forward-clicked with IR equal to curated must not mark as mutated.

        Regression guard: the editor pre-fills with curated_ir, so a user
        who opens and immediately submits should produce no "Edited" badge.
        """
        curated = _make_ir(message_text="hello")
        unchanged = _make_ir(message_text="hello")
        assert curated == unchanged  # Pydantic v2 structural equality
        final_ir, mutated, audit = _resolve_paused_flow(
            self._paused(curated, unchanged)
        )
        assert final_ir is unchanged
        assert mutated is False
        assert audit is None

    def test_forward_with_edits_reports_mutation(self) -> None:
        """A genuine edit produces mutated=True."""
        curated = _make_ir(message_text="hello")
        edited = _make_ir(message_text="hello world")
        assert curated != edited
        final_ir, mutated, audit = _resolve_paused_flow(self._paused(curated, edited))
        assert final_ir is edited
        assert mutated is True
        assert audit is None

    def test_pass_through_returns_live_pf_audit(self) -> None:
        """Regression: audit-refresh bug.

        The addon used to snapshot ``manicure_audit`` from ``_run_pipeline``
        at request ingress and never refresh it, even after the user edited
        overrides during the pause. ``_update_paused_preview`` re-runs
        ``apply_overrides`` and mutates ``pf.audit`` in place, so the
        authoritative state lives on the paused flow. On a Pass Through
        release we must forward that live audit so the Inspect tab sees the
        post-pause ``overrides_applied`` list and doesn't fall back to the
        structural-diff path (which re-exposes the pop-cascade bug).
        """
        curated = _make_ir(message_text="hello")
        live_audit = OverrideAudit(
            entries=[
                OverrideAuditEntry(
                    kind="message_text",
                    target="msg:0:blk:0",
                    applied=True,
                    chars_delta=-5,
                    curated_value="hi",
                )
            ],
            chars_before=5,
            chars_after=2,
        )
        _final_ir, mutated, audit = _resolve_paused_flow(
            self._paused(curated, None, audit=live_audit)
        )
        assert mutated is False
        assert audit is live_audit

    def test_forward_unchanged_returns_live_pf_audit(self) -> None:
        """Forward-clicked with IR equal to curated still exposes the live audit.

        The editor pre-fill plus no-op submission lands here. The audit still
        describes the IR that shipped (== curated_ir), so it must ride along.
        """
        curated = _make_ir(message_text="hello")
        unchanged = _make_ir(message_text="hello")
        live_audit = OverrideAudit(entries=[], chars_before=0, chars_after=0)
        _final_ir, mutated, audit = _resolve_paused_flow(
            self._paused(curated, unchanged, audit=live_audit)
        )
        assert mutated is False
        assert audit is live_audit

    def test_forward_with_edits_drops_audit(self) -> None:
        """Manual textarea edits desynchronize pf.audit from the shipped IR.

        ``pf.audit`` is computed against ``pf.curated_ir``. When the user
        hand-edits in the textareas, the shipped IR is ``pf.mutated_ir`` —
        a different payload. Keeping the mismatched audit would make the
        Inspect tab render a diff that doesn't match reality. None lets
        the UI fall through to the structural-diff path, which works
        correctly for manual edits (they don't pop blocks, so no cascade).
        """
        curated = _make_ir(message_text="hello")
        edited = _make_ir(message_text="hello world")
        live_audit = OverrideAudit(entries=[], chars_before=0, chars_after=0)
        _final_ir, mutated, audit = _resolve_paused_flow(
            self._paused(curated, edited, audit=live_audit)
        )
        assert mutated is True
        assert audit is None
