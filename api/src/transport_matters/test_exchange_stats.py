"""Tests for exchange_stats helpers."""

from __future__ import annotations

from transport_matters.exchange_stats import (
    extract_response_text,
    extract_user_prompt_text,
    stamp_pipeline_tokens,
)
from transport_matters.ir import (
    ContentBlock,
    InternalRequest,
    InternalResponse,
    Message,
    RequestMetadata,
    SamplingParams,
    SystemPart,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
    UsageStats,
)
from transport_matters.storage import PipelineStats


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


class _CountAdapter:
    def __init__(self) -> None:
        self.outbound_calls = 0

    def outbound_request(self, ir: InternalRequest) -> bytes:
        self.outbound_calls += 1
        return f"serialized:{ir.system}".encode()


class _SeqCounter:
    def __init__(self) -> None:
        self.calls = 0

    async def count(self, payload: bytes, auth_headers: dict[str, str]) -> int | None:
        self.calls += 1
        return len(payload)


async def test_stamp_pipeline_tokens_skips_curated_serialization_when_unchanged() -> (
    None
):
    adapter = _CountAdapter()
    counter = _SeqCounter()
    ir = _make_ir([_user([TextBlock(text="hi")])])
    stats = PipelineStats(overrides_applied=[], chars_before=10, chars_after=10)

    result = await stamp_pipeline_tokens(stats, ir, ir, adapter, counter, {})

    # No-op pipeline: only the original is serialized and counted once.
    assert adapter.outbound_calls == 1
    assert counter.calls == 1
    assert result.tokens_before == result.tokens_after


async def test_stamp_pipeline_tokens_counts_both_sides_when_changed() -> None:
    adapter = _CountAdapter()
    counter = _SeqCounter()
    original = _make_ir([_user([TextBlock(text="hi")])])
    curated = original.model_copy(update={"system": [SystemPart(text="injected")]})
    stats = PipelineStats(overrides_applied=[], chars_before=10, chars_after=20)

    result = await stamp_pipeline_tokens(stats, original, curated, adapter, counter, {})

    assert adapter.outbound_calls == 2
    assert counter.calls == 2
    assert result.tokens_before is not None
    assert result.tokens_after is not None


class _RaisingResponseAdapter:
    def inbound_response(self, raw: bytes, content_type: str) -> object:
        raise ValueError("unparsable response shape")


def test_parse_response_ir_marks_unparsable_response() -> None:
    from transport_matters.exchange_stats import _parse_response_ir

    res_ir, res_stats = _parse_response_ir(
        _RaisingResponseAdapter(), b"<<garbage>>", "application/json", "ex-1"
    )
    assert res_ir is None
    assert res_stats is not None
    assert res_stats.stop_reason == "response_parse_failure"
