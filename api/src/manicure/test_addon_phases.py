"""Tests for decomposed addon phase helpers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any  # Any: opaque rule dicts match StorageBackend API

from manicure import broadcast
from manicure.addon import (
    _build_pipeline_stats,
    _build_req_stats,
    _emit_exchange,
    _parse_sse_stats,
    _run_pipeline,
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
from manicure.rules import Rule, RuleAuditEntry, RuleScope
from manicure.storage.base import PipelineStats
from manicure.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class _FailingModifyStorage(DiskStorageBackend):
    """DiskStorageBackend whose modify_rules always raises.

    Used to test that _run_pipeline preserves its pipeline output when the
    applied_count bookkeeping write fails.
    """

    async def modify_rules(
        self,
        fn: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    ) -> None:
        msg = "simulated disk failure"
        raise OSError(msg)


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


# ── _run_pipeline concurrency ───────────────────────────────────────


def _make_global_rule(rule_id: str, name: str) -> Rule:
    """Eligible, no-op global rule: matches every IR, removes nothing."""
    return Rule(
        id=rule_id,
        name=name,
        enabled=True,
        scope=RuleScope(global_=True),
        action="strip_tools",
        params={"name": "tool-name-that-never-matches"},
    )


async def test_run_pipeline_bump_survives_concurrent_delete(tmp_path: Path) -> None:
    """_run_pipeline's applied_count bump must not resurrect a concurrently-deleted rule.

    Regression for the old load_rules+save_rules RMW: under that implementation a
    user DELETE that interleaved between the pipeline's read and write was
    silently undone, because save_rules would write back the stale list including
    the deleted rule. With modify_rules the bump iterates over fresh state inside
    the lock, so any rule absent from that fresh state stays absent.
    """
    storage = DiskStorageBackend(root=str(tmp_path))

    firing_rule = _make_global_rule("r-firing", "firing")
    victim_rule = _make_global_rule("r-victim", "victim")

    def _seed(_: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            firing_rule.model_dump(mode="json", by_alias=True),
            victim_rule.model_dump(mode="json", by_alias=True),
        ]

    await storage.modify_rules(_seed)

    ir = _make_ir()

    def _delete_victim(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [r for r in data if r.get("id") != "r-victim"]

    await asyncio.gather(
        _run_pipeline(storage, ir, "test-flow"),
        storage.modify_rules(_delete_victim),
    )

    loaded = await storage.load_rules()
    ids = {r["id"] for r in loaded}
    assert "r-victim" not in ids, (
        "Pipeline's applied_count bump resurrected a concurrently-deleted rule"
    )
    assert "r-firing" in ids
    firing_loaded = next(r for r in loaded if r["id"] == "r-firing")
    assert firing_loaded["applied_count"] == 1


async def test_run_pipeline_preserves_output_when_bump_fails(
    tmp_path: Path,
) -> None:
    """A failed applied_count bump must not invalidate the pipeline's curated IR.

    The pipeline read+apply and the counter bump are independent concerns.
    If modify_rules raises (e.g. disk I/O failure), we still return the
    curated IR so the proxy forwards the transformed request.
    """
    # Seed via a real backend so the on-disk rules.json has one rule.
    seed_storage = DiskStorageBackend(root=str(tmp_path))
    rule = _make_global_rule("r1", "rule-1")
    await seed_storage.modify_rules(
        lambda _: [rule.model_dump(mode="json", by_alias=True)]
    )

    # Read via a backend whose modify_rules always raises.
    failing = _FailingModifyStorage(root=str(tmp_path))
    curated_ir, audit = await _run_pipeline(failing, _make_ir(), "test-flow")

    # Pipeline output is preserved even though the bump failed.
    assert curated_ir is not None
    assert audit is not None
    assert len(audit.rules_applied) == 1


class TestEmitExchange:
    """_emit_exchange SSE payload includes mutated_manually and pipeline fields."""

    def setup_method(self) -> None:
        broadcast._subscribers.clear()

    def teardown_method(self) -> None:
        broadcast._subscribers.clear()

    def test_payload_includes_mutated_manually_and_pipeline(self) -> None:
        import json
        from datetime import UTC, datetime

        ir = _make_ir()
        req_stats = _build_req_stats(ir)
        pipeline_stats = PipelineStats(
            rules_applied=[],
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
