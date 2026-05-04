"""Tests for exchange_stats helpers."""

from __future__ import annotations

from transport_matters.exchange_stats import (
    extract_response_text,
    extract_user_prompt_text,
)
from transport_matters.ir import (
    ContentBlock,
    InternalRequest,
    InternalResponse,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
    UsageStats,
)


def _make_ir(messages: list[Message]) -> InternalRequest:
    return InternalRequest(
        model="claude-opus-4-7",
        provider="anthropic",
        system=[],
        tools=[],
        messages=messages,
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


def _user(content: list[ContentBlock]) -> Message:
    return Message(role="user", content=content)


def _assistant(text: str = "ok") -> Message:
    return Message(role="assistant", content=[TextBlock(text=text)])


def _make_res(
    content: list[TextBlock | ToolUseBlock | ThinkingBlock | UnknownBlock],
) -> InternalResponse:
    return InternalResponse(
        id="msg_test",
        model="claude-opus-4-7",
        provider="anthropic",
        content=content,
        stop_reason="end_turn",
        usage=UsageStats(input_tokens=0, output_tokens=0),
    )


def test_extract_response_text_returns_text_blocks() -> None:
    res = _make_res([TextBlock(text="hello"), TextBlock(text="world")])
    assert extract_response_text(res) == "hello\nworld"


def test_extract_response_text_falls_back_to_tool_use_input_json() -> None:
    res = _make_res(
        [ToolUseBlock(id="toolu_01", name="Read", input={"path": "/tmp/x"})]
    )
    assert extract_response_text(res) == '{"path": "/tmp/x"}'


def test_extract_response_text_prefers_text_over_tool_use() -> None:
    res = _make_res(
        [
            ToolUseBlock(id="toolu_01", name="Read", input={"path": "/tmp/x"}),
            TextBlock(text="answer"),
        ]
    )
    assert extract_response_text(res) == "answer"


def test_extract_response_text_wraps_thinking_block_in_xml() -> None:
    res = _make_res([ThinkingBlock(text="reasoning step")])
    assert extract_response_text(res) == "<thinking>reasoning step</thinking>"


def test_extract_response_text_returns_none_when_empty() -> None:
    res = _make_res([])
    assert extract_response_text(res) is None


def test_extract_response_text_returns_none_when_only_unknown() -> None:
    res = _make_res([UnknownBlock(raw={"foo": "bar"})])
    assert extract_response_text(res) is None


def test_extract_response_text_skips_empty_thinking_block() -> None:
    res = _make_res([ThinkingBlock(text="")])
    assert extract_response_text(res) is None


def test_extract_user_prompt_text_returns_full_text_uncapped() -> None:
    long = "x" * 5000
    ir = _make_ir([_user([TextBlock(text=long)])])
    assert extract_user_prompt_text(ir) == long


def test_extract_user_prompt_text_strips_outer_whitespace() -> None:
    ir = _make_ir([_user([TextBlock(text="  hi  ")])])
    assert extract_user_prompt_text(ir) == "hi"


def test_extract_user_prompt_text_returns_none_when_no_user_message() -> None:
    ir = _make_ir([_assistant("only assistant")])
    assert extract_user_prompt_text(ir) is None


def test_extract_user_prompt_text_falls_back_to_tool_result_text() -> None:
    tool_result = ToolResultBlock(
        tool_use_id="toolu_01",
        content=[TextBlock(text="tool output")],
    )
    ir = _make_ir([_user([tool_result])])
    assert extract_user_prompt_text(ir) == "tool output"
