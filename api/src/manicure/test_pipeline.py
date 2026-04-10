"""Tests for the pipeline engine."""

from __future__ import annotations

from datetime import UTC, datetime

from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
    ThinkingBlock,
    ToolDef,
)
from manicure.pipeline import apply
from manicure.rules import Rule, RuleScope


def _make_ir(
    tools: list[ToolDef] | None = None,
    messages: list[Message] | None = None,
    model: str = "anthropic/claude-sonnet-4-20250514",
    metadata: RequestMetadata | None = None,
) -> InternalRequest:
    return InternalRequest(
        model=model,
        provider="anthropic",
        system=[],
        tools=tools or [],
        messages=messages or [Message(role="user", content=[TextBlock(text="hi")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=metadata or RequestMetadata(),
    )


def _tool(name: str) -> ToolDef:
    return ToolDef(name=name, description="A tool", input_schema={"type": "object"})


class TestApply:
    def test_apply_no_rules(self) -> None:
        ir = _make_ir()
        new_ir, audit = apply([], ir)
        assert new_ir == ir
        assert audit.rules_applied == []
        assert audit.chars_before == audit.chars_after

    def test_apply_single_rule(self) -> None:
        ir = _make_ir(
            messages=[
                Message(
                    role="assistant",
                    content=[
                        ThinkingBlock(text="hmm"),
                        TextBlock(text="Hello"),
                    ],
                ),
            ]
        )
        rule = Rule(
            name="strip-think",
            scope=RuleScope(global_=True),
            action="strip_thinking",
            params={},
        )
        new_ir, audit = apply([rule], ir)
        assert len(audit.rules_applied) == 1
        assert audit.rules_applied[0].action == "strip_thinking"
        assert audit.rules_applied[0].removed["blocks"] == 1
        # Thinking block text was removed, so chars_after < chars_before
        assert audit.chars_after < audit.chars_before

    def test_apply_ordering(self) -> None:
        """Rules are applied in created_at order, regardless of list order."""
        ir = _make_ir(
            tools=[_tool("mcp_read"), _tool("bash")],
            messages=[
                Message(
                    role="assistant",
                    content=[ThinkingBlock(text="think"), TextBlock(text="ok")],
                ),
            ],
        )
        early = Rule(
            name="strip-thinking-first",
            scope=RuleScope(global_=True),
            action="strip_thinking",
            params={},
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        late = Rule(
            name="strip-tools-second",
            scope=RuleScope(global_=True),
            action="strip_tools",
            params={"prefix": "mcp_"},
            created_at=datetime(2025, 6, 1, tzinfo=UTC),
        )
        # Pass in reverse order; pipeline should still apply early first
        _, audit = apply([late, early], ir)
        assert audit.rules_applied[0].name == "strip-thinking-first"
        assert audit.rules_applied[1].name == "strip-tools-second"

    def test_apply_disabled_rule_skipped(self) -> None:
        ir = _make_ir(
            messages=[
                Message(
                    role="assistant",
                    content=[ThinkingBlock(text="x"), TextBlock(text="y")],
                ),
            ]
        )
        rule = Rule(
            name="disabled",
            scope=RuleScope(global_=True),
            action="strip_thinking",
            params={},
            enabled=False,
        )
        new_ir, audit = apply([rule], ir)
        assert len(audit.rules_applied) == 0
        # Thinking block should still be there
        assert len(new_ir.messages[0].content) == 2

    def test_apply_scope_filtered(self) -> None:
        ir = _make_ir(metadata=RequestMetadata(device_id="dev-A"))
        rule = Rule(
            name="other-device",
            scope=RuleScope(device_id="dev-B"),
            action="strip_thinking",
            params={},
        )
        _, audit = apply([rule], ir)
        assert len(audit.rules_applied) == 0
