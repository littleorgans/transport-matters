"""Tests for exchange_stats helpers."""

from __future__ import annotations

from manicure.exchange_stats import extract_user_prompt_preview
from manicure.ir import (
    ContentBlock,
    ImageBlock,
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
    ToolResultBlock,
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


def test_extract_preview_returns_last_user_text() -> None:
    ir = _make_ir([_user([TextBlock(text="hello world")])])
    assert extract_user_prompt_preview(ir) == "hello world"


def test_extract_preview_returns_last_user_message() -> None:
    ir = _make_ir(
        [
            _user([TextBlock(text="first")]),
            _assistant(),
            _user([TextBlock(text="second")]),
        ]
    )
    assert extract_user_prompt_preview(ir) == "second"


def test_extract_preview_truncates_at_max_chars() -> None:
    long = "x" * 1500
    ir = _make_ir([_user([TextBlock(text=long)])])
    result = extract_user_prompt_preview(ir)
    assert result == "x" * 1000 + "\u2026"
    assert len(result) == 1001


def test_extract_preview_strips_outer_whitespace() -> None:
    ir = _make_ir([_user([TextBlock(text="  hello  ")])])
    assert extract_user_prompt_preview(ir) == "hello"


def test_extract_preview_none_when_no_user_message() -> None:
    ir = _make_ir([_assistant("only assistant")])
    assert extract_user_prompt_preview(ir) is None


def test_extract_preview_falls_back_to_tool_result_text() -> None:
    tool_result = ToolResultBlock(
        tool_use_id="toolu_01",
        content=[TextBlock(text='{"status": "ok", "items": [1, 2, 3]}')],
    )
    ir = _make_ir(
        [
            _user([TextBlock(text="initial")]),
            _assistant(),
            _user([tool_result]),
        ]
    )
    assert extract_user_prompt_preview(ir) == '{"status": "ok", "items": [1, 2, 3]}'


def test_extract_preview_joins_multi_text_tool_result() -> None:
    tool_result = ToolResultBlock(
        tool_use_id="toolu_01",
        content=[TextBlock(text="line one"), TextBlock(text="line two")],
    )
    ir = _make_ir([_user([tool_result])])
    assert extract_user_prompt_preview(ir) == "line one\nline two"


def test_extract_preview_prefers_trailing_text_over_tool_result() -> None:
    tool_result = ToolResultBlock(
        tool_use_id="toolu_01",
        content=[TextBlock(text="tool output")],
    )
    ir = _make_ir([_user([tool_result, TextBlock(text="follow-up prompt")])])
    assert extract_user_prompt_preview(ir) == "follow-up prompt"


def test_extract_preview_falls_back_to_tool_result_when_text_empty() -> None:
    tool_result = ToolResultBlock(
        tool_use_id="toolu_01",
        content=[TextBlock(text="actual content")],
    )
    ir = _make_ir([_user([TextBlock(text=""), tool_result])])
    assert extract_user_prompt_preview(ir) == "actual content"


def test_extract_preview_none_when_only_image_in_user_message() -> None:
    image = ImageBlock(source={"type": "base64", "data": "..."})
    ir = _make_ir([_user([image])])
    assert extract_user_prompt_preview(ir) is None


def test_extract_preview_none_when_only_tool_use_blocks() -> None:
    tool_result = ToolResultBlock(
        tool_use_id="toolu_01",
        content=[ImageBlock(source={"type": "base64", "data": "..."})],
    )
    ir = _make_ir([_user([tool_result])])
    assert extract_user_prompt_preview(ir) is None
