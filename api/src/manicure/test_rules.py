"""Tests for rule actions and scope matching."""

from __future__ import annotations

from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
    ThinkingBlock,
    ToolDef,
    ToolResultBlock,
)
from manicure.rules import (
    Rule,
    RuleScope,
    matches_scope,
    rewrite_tool_description,
    strip_system_part,
    strip_thinking,
    strip_tools,
    truncate_system_part,
    truncate_tool_result,
)


def _make_ir(
    tools: list[ToolDef] | None = None,
    messages: list[Message] | None = None,
    system: list[SystemPart] | None = None,
    model: str = "anthropic/claude-sonnet-4-20250514",
    metadata: RequestMetadata | None = None,
) -> InternalRequest:
    return InternalRequest(
        model=model,
        provider="anthropic",
        system=system or [],
        tools=tools or [],
        messages=messages or [Message(role="user", content=[TextBlock(text="hi")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=metadata or RequestMetadata(),
    )


def _tool(name: str, desc: str = "A tool") -> ToolDef:
    return ToolDef(name=name, description=desc, input_schema={"type": "object"})


class TestStripTools:
    def test_strip_tools_by_prefix(self) -> None:
        ir = _make_ir(tools=[_tool("mcp_read"), _tool("mcp_write"), _tool("bash")])
        new_ir, audit = strip_tools(ir, {"prefix": "mcp_"})
        assert len(new_ir.tools) == 1
        assert new_ir.tools[0].name == "bash"
        assert audit["tools"] == 2
        assert audit["chars"] > 0

    def test_strip_tools_by_name(self) -> None:
        ir = _make_ir(tools=[_tool("bash"), _tool("read")])
        new_ir, audit = strip_tools(ir, {"name": "bash"})
        assert len(new_ir.tools) == 1
        assert new_ir.tools[0].name == "read"
        assert audit["tools"] == 1

    def test_strip_tools_by_regex(self) -> None:
        ir = _make_ir(tools=[_tool("mcp_read"), _tool("mcp_write"), _tool("bash")])
        new_ir, audit = strip_tools(ir, {"regex": r"^mcp_.*"})
        assert len(new_ir.tools) == 1
        assert new_ir.tools[0].name == "bash"
        assert audit["tools"] == 2


class TestStripThinking:
    def test_strip_thinking(self) -> None:
        messages = [
            Message(
                role="assistant",
                content=[
                    ThinkingBlock(text="Let me think..."),
                    TextBlock(text="Hello"),
                ],
            ),
        ]
        ir = _make_ir(messages=messages)
        new_ir, audit = strip_thinking(ir, {})
        assert len(new_ir.messages[0].content) == 1
        assert audit["blocks"] == 1
        assert audit["chars"] == len("Let me think...")


class TestStripSystemPart:
    def test_strip_system_part(self) -> None:
        system = [SystemPart(text="First"), SystemPart(text="Second")]
        ir = _make_ir(system=system)
        new_ir, audit = strip_system_part(ir, {"index": 0})
        assert len(new_ir.system) == 1
        assert new_ir.system[0].text == "Second"
        assert audit["parts"] == 1
        assert audit["chars"] == len("First")

    def test_strip_system_part_out_of_range(self) -> None:
        system = [SystemPart(text="Only")]
        ir = _make_ir(system=system)
        new_ir, audit = strip_system_part(ir, {"index": 5})
        assert len(new_ir.system) == 1
        assert audit["parts"] == 0
        assert audit["chars"] == 0


class TestTruncateSystemPart:
    def test_truncate_system_part(self) -> None:
        long_text = "x" * 1000
        system = [SystemPart(text=long_text)]
        ir = _make_ir(system=system)
        new_ir, audit = truncate_system_part(ir, {"index": 0, "max_chars": 100})
        assert new_ir.system[0].text == "x" * 100 + " [truncated]"
        assert audit["chars"] > 0


class TestTruncateToolResult:
    def test_truncate_tool_result_by_turns(self) -> None:
        messages = [
            Message(
                role="user",
                content=[
                    ToolResultBlock(
                        tool_use_id="tu1",
                        content=[TextBlock(text="x" * 5000)],
                    ),
                ],
            ),
            Message(role="assistant", content=[TextBlock(text="ok")]),
            Message(role="user", content=[TextBlock(text="next")]),
            Message(role="assistant", content=[TextBlock(text="ok2")]),
            Message(role="user", content=[TextBlock(text="latest")]),
        ]
        ir = _make_ir(messages=messages)
        new_ir, audit = truncate_tool_result(ir, {"older_than_turns": 2})
        # The first user message (turn 1) is old enough to truncate
        first_user = new_ir.messages[0]
        result_block = first_user.content[0]
        assert hasattr(result_block, "content")
        assert result_block.content[0].text.endswith(" [truncated]")  # type: ignore[union-attr]
        assert audit["blocks"] == 1

    def test_truncate_tool_result_by_chars(self) -> None:
        messages = [
            Message(
                role="user",
                content=[
                    ToolResultBlock(
                        tool_use_id="tu1",
                        content=[TextBlock(text="x" * 5000)],
                    ),
                ],
            ),
        ]
        ir = _make_ir(messages=messages)
        new_ir, audit = truncate_tool_result(ir, {"max_chars": 100})
        result_block = new_ir.messages[0].content[0]
        assert result_block.content[0].text == "x" * 100 + " [truncated]"  # type: ignore[union-attr]
        assert audit["blocks"] == 1
        assert audit["chars"] > 0


class TestRewriteToolDescription:
    def test_rewrite_tool_description(self) -> None:
        ir = _make_ir(tools=[_tool("bash", desc="Run a bash command")])
        new_ir, audit = rewrite_tool_description(
            ir, {"name": "bash", "new": "Execute shell"}
        )
        assert new_ir.tools[0].description == "Execute shell"
        expected_delta = len("Execute shell") - len("Run a bash command")
        assert audit["chars"] == expected_delta


class TestMatchesScope:
    def test_matches_scope_global(self) -> None:
        rule = Rule(
            name="test",
            scope=RuleScope(global_=True),
            action="strip_thinking",
            params={},
        )
        ir = _make_ir()
        assert matches_scope(rule, ir) is True

    def test_matches_scope_device_id(self) -> None:
        rule = Rule(
            name="test",
            scope=RuleScope(device_id="dev-123"),
            action="strip_thinking",
            params={},
        )
        ir = _make_ir(metadata=RequestMetadata(device_id="dev-123"))
        assert matches_scope(rule, ir) is True

    def test_matches_scope_no_match(self) -> None:
        rule = Rule(
            name="test",
            scope=RuleScope(device_id="dev-999"),
            action="strip_thinking",
            params={},
        )
        ir = _make_ir(metadata=RequestMetadata(device_id="dev-123"))
        assert matches_scope(rule, ir) is False
