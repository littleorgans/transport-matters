"""Shared fixture tests for override target grammar."""

import json
from pathlib import Path
from typing import Any, cast

from transport_matters.override_targets import (
    message_block_target,
    parse_message_target,
    parse_provider_extras_key,
    parse_sampling_field,
    parse_system_index,
    parse_tool_name,
    parse_tool_result_id,
    provider_extras_target,
    sampling_target,
    system_target,
    tool_result_target,
    tool_target,
)


def _fixture() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[3] / "shared" / "override_targets_v1.json"
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def test_shared_override_target_builders_match_fixture() -> None:
    fixture = _fixture()["builders"]

    for case in fixture["tool"]:
        assert tool_target(case["value"]) == case["target"]
    for case in fixture["system"]:
        assert system_target(case["index"]) == case["target"]
    for case in fixture["tool_result"]:
        assert tool_result_target(case["value"]) == case["target"]
    for case in fixture["sampling"]:
        assert sampling_target(case["value"]) == case["target"]
    for case in fixture["provider_extras"]:
        assert provider_extras_target(case["value"]) == case["target"]
    for case in fixture["message_block"]:
        assert message_block_target(case["msg_idx"], case["blk_idx"]) == case["target"]


def test_shared_override_target_parsers_match_fixture() -> None:
    fixture = _fixture()["parsers"]

    for case in fixture["tool"]:
        assert parse_tool_name(case["target"]) == case["value"]
    for case in fixture["system"]:
        assert parse_system_index(case["target"]) == case["value"]
    for case in fixture["tool_result"]:
        assert parse_tool_result_id(case["target"]) == case["value"]
    for case in fixture["sampling"]:
        assert parse_sampling_field(case["target"]) == case["value"]
    for case in fixture["provider_extras"]:
        assert parse_provider_extras_key(case["target"]) == case["value"]
    for case in fixture["message_block"]:
        expected = None if case["value"] is None else tuple(case["value"])
        assert parse_message_target(case["target"]) == expected
