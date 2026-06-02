"""Tests for override audit behavior."""

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from transport_matters.ir import (
    ContentBlock,
    InternalRequest,
    Message,
    SystemPart,
    TextBlock,
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
)
from transport_matters.override_audit import (
    canonical_block_json,
    canonical_json,
    count_chars_parts,
    tool_chars,
)
from transport_matters.overrides import Override, apply_overrides, get_store
from transport_matters.test_override_support import TOOL_BASH, TOOL_READ, make_ir


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    store = get_store()
    store.clear()
    store.enabled = True


class TestAuditAggregate:
    def test_chars_before_after(self) -> None:
        ir = make_ir(tools=[TOOL_BASH, TOOL_READ])
        overrides = [Override(kind="tool_toggle", target="tool:mcp_bash", value=False)]
        _, audit = apply_overrides(overrides, ir)
        assert audit.chars_before > audit.chars_after
        assert audit.chars_delta < 0

    def test_no_overrides_identity(self) -> None:
        ir = make_ir()
        result, audit = apply_overrides([], ir)
        assert result == ir
        assert audit.entries == []
        assert audit.chars_before == audit.chars_after

    def test_shared_char_accounting_fixture_matches_contract(self) -> None:
        fixture_path = Path(__file__).resolve().parents[3] / "shared" / "char_accounting_v1.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        expected = fixture["expected"]
        block_adapter: TypeAdapter[ContentBlock] = TypeAdapter(ContentBlock)

        assert canonical_json(fixture["numbers"]) == expected["numbers_json"]
        for number_case in fixture["number_cases"]:
            raw_value = number_case["value"]
            value = int(raw_value) if number_case["kind"] == "int" else float(raw_value)
            assert canonical_json(value) == number_case["expected"], number_case["label"]
        for residual_case in fixture["production_number_residual_cases"]:
            assert (
                canonical_json(json.loads(residual_case["json"]))
                == residual_case["python_expected"]
            ), residual_case["label"]
            assert residual_case["python_expected"] != residual_case["typescript_expected"], (
                residual_case["label"]
            )
        assert canonical_json(fixture["tool"]["input_schema"]) == expected["tool_input_schema_json"]
        tool = ToolDef.model_validate(fixture["tool"])
        assert tool_chars(tool) == expected["tool_chars"]

        for name, block in fixture["blocks"].items():
            parsed = block_adapter.validate_python(block)
            assert canonical_block_json(parsed) == expected["blocks"][name]

        ir = InternalRequest.model_validate(fixture["internal_request"])
        system, tools, messages = count_chars_parts(ir)
        assert {
            "system": system,
            "tools": tools,
            "messages": messages,
            "total": system + tools + messages,
        } == expected["parts"]

    def test_canonical_json_sorts_keys_by_code_point(self) -> None:
        assert canonical_json({"\ue000": 1, "😀": 2}) == '{"\ue000":1,"😀":2}'

    def test_canonical_json_rejects_non_finite_numbers(self) -> None:
        with pytest.raises(ValueError, match="non-finite"):
            canonical_json(float("nan"))
        with pytest.raises(ValueError, match="non-finite"):
            canonical_json(float("inf"))


class TestAuditCuratedValue:
    """Audit tracks the curated text for text-bearing override kinds."""

    def test_system_part_text_populates(self) -> None:
        ir = make_ir(system=[SystemPart(text="part-0")])
        overrides = [Override(kind="system_part_text", target="system:0", value="rewritten")]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is True
        assert audit.entries[0].curated_value == "rewritten"

    def test_tool_description_populates(self) -> None:
        ir = make_ir(tools=[TOOL_BASH])
        overrides = [
            Override(
                kind="tool_description",
                target="tool:mcp_bash",
                value="Run commands safely",
            )
        ]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is True
        assert audit.entries[0].curated_value == "Run commands safely"

    def test_message_text_populates(self) -> None:
        messages = [Message(role="user", content=[TextBlock(text="hi")])]
        ir = make_ir(messages=messages)
        overrides = [Override(kind="message_text", target="msg:0:blk:0", value="hello")]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is True
        assert audit.entries[0].curated_value == "hello"

    def test_truncate_tool_result_populates_with_truncated_text(self) -> None:
        messages = [
            Message(
                role="assistant",
                content=[ToolUseBlock(id="tu-1", name="bash", input={})],
            ),
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="tu-1", content=[TextBlock(text="a" * 500)])],
            ),
        ]
        ir = make_ir(messages=messages)
        overrides = [Override(kind="truncate_tool_result", target="toolresult:tu-1", value=100)]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is True
        assert audit.entries[0].curated_value == "a" * 100 + " [truncated]"

    def test_truncate_tool_result_short_text_untouched(self) -> None:
        messages = [
            Message(
                role="assistant",
                content=[ToolUseBlock(id="tu-1", name="bash", input={})],
            ),
            Message(
                role="user",
                content=[ToolResultBlock(tool_use_id="tu-1", content=[TextBlock(text="tiny")])],
            ),
        ]
        ir = make_ir(messages=messages)
        overrides = [Override(kind="truncate_tool_result", target="toolresult:tu-1", value=100)]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is True
        assert audit.entries[0].curated_value == "tiny"

    def test_toggle_kinds_leave_curated_value_none(self) -> None:
        messages = [Message(role="user", content=[TextBlock(text="a"), TextBlock(text="b")])]
        ir = make_ir(
            system=[SystemPart(text="sys")],
            tools=[TOOL_BASH],
            messages=messages,
        ).model_copy(update={"provider_extras": {}})
        overrides = [
            Override(kind="tool_toggle", target="tool:mcp_bash", value=False),
            Override(kind="system_part_toggle", target="system:0", value=False),
            Override(kind="message_block_toggle", target="msg:0:blk:1", value=False),
            Override(kind="sampling_set", target="sampling:max_tokens", value="42"),
            Override(
                kind="provider_extras_set",
                target="provider_extras:thinking",
                value='"on"',
            ),
        ]
        _, audit = apply_overrides(overrides, ir)
        for entry in audit.entries:
            assert entry.applied is True, f"{entry.kind} {entry.target}"
            assert entry.curated_value is None, f"{entry.kind} {entry.target}"

    def test_unapplied_text_override_leaves_curated_value_none(self) -> None:
        ir = make_ir(messages=[Message(role="user", content=[TextBlock(text="hi")])])
        overrides = [Override(kind="message_text", target="msg:0:blk:99", value="nope")]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert audit.entries[0].curated_value is None

    def test_unapplied_truncate_leaves_curated_value_none(self) -> None:
        ir = make_ir()
        overrides = [Override(kind="truncate_tool_result", target="toolresult:missing", value=100)]
        _, audit = apply_overrides(overrides, ir)
        assert audit.entries[0].applied is False
        assert audit.entries[0].curated_value is None
