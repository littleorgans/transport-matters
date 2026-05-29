from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard

REPO_ROOT = Path(__file__).resolve().parents[3]
PY_IR = Path(__file__).with_name("ir.py")
PY_OVERRIDES = Path(__file__).with_name("overrides.py")
TS_TYPES = REPO_ROOT / "www" / "src" / "types.ts"

BLOCK_MODELS = frozenset(
    {
        "TextBlock",
        "ToolUseBlock",
        "ToolResultBlock",
        "ThinkingBlock",
        "ImageBlock",
        "UnknownBlock",
    },
)

MIRRORED_MODELS = (
    "TextBlock",
    "ToolUseBlock",
    "ToolResultBlock",
    "ThinkingBlock",
    "ImageBlock",
    "UnknownBlock",
    "SystemPart",
    "ToolDef",
    "Message",
    "SamplingParams",
    "RequestMetadata",
    "InternalRequest",
    "UsageStats",
    "InternalResponse",
)

NULLABLE_PROVIDER_MODELS = (
    "TextBlock",
    "ToolUseBlock",
    "ToolResultBlock",
    "ThinkingBlock",
    "ImageBlock",
    "SystemPart",
    "ToolDef",
    "Message",
)

NULLABLE_RECORD = "Record<string, unknown> | null"
EXPECTED_RESPONSE_BLOCKS = {
    "TextBlock",
    "ToolUseBlock",
    "ThinkingBlock",
    "UnknownBlock",
}
EXPECTED_TOOL_RESULT_BLOCKS = {"TextBlock", "ImageBlock", "UnknownBlock"}


@dataclass(frozen=True)
class TsField:
    type: str
    optional: bool


def test_override_kind_values_match_in_order() -> None:
    py_values = _py_literal_values(PY_OVERRIDES.read_text(), "OverrideKind")
    ts_values = _ts_type_values(TS_TYPES.read_text(), "OverrideKind")

    assert ts_values == py_values


def test_ir_model_field_sets_match() -> None:
    py_fields = _py_model_fields(PY_IR.read_text())
    ts_fields = _ts_interface_fields(TS_TYPES.read_text())

    for model_name in MIRRORED_MODELS:
        assert set(ts_fields[model_name]) == set(py_fields[model_name]), model_name


def test_content_block_union_matches_python_ir() -> None:
    py_blocks = _py_assignment_blocks(PY_IR.read_text(), "ContentBlock")
    ts_blocks = _ts_type_blocks(TS_TYPES.read_text(), "ContentBlock")

    assert ts_blocks == py_blocks


def test_targeted_type_mirror_contracts() -> None:
    ts_fields = _ts_interface_fields(TS_TYPES.read_text())

    assert _field(ts_fields, "Message", "role").type == "string"
    assert "provider_data" not in ts_fields["UnknownBlock"]

    for model_name in NULLABLE_PROVIDER_MODELS:
        field = _field(ts_fields, model_name, "provider_data")
        assert field == TsField(type=NULLABLE_RECORD, optional=True)

    assert _field(ts_fields, "SystemPart", "cache_hint") == TsField(
        type=NULLABLE_RECORD,
        optional=True,
    )
    assert _field_blocks(ts_fields, "ToolResultBlock", "content") == (
        EXPECTED_TOOL_RESULT_BLOCKS
    )
    assert _field_blocks(ts_fields, "InternalResponse", "content") == (
        EXPECTED_RESPONSE_BLOCKS
    )
    assert "ContentBlock" not in _field(ts_fields, "InternalResponse", "content").type


def _py_literal_values(source: str, name: str) -> list[str]:
    tree = ast.parse(source)
    for node in tree.body:
        if not _is_assignment_to(node, name):
            continue
        values: list[str] = []
        for child in ast.walk(node.value):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                values.append(child.value)
        return values
    raise AssertionError(f"Missing Python literal assignment {name}")


def _py_model_fields(source: str) -> dict[str, dict[str, str]]:
    tree = ast.parse(source)
    fields: dict[str, dict[str, str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in MIRRORED_MODELS:
            continue
        fields[node.name] = {
            statement.target.id: ast.get_source_segment(source, statement.annotation)
            or ""
            for statement in node.body
            if isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
        }
    return fields


def _py_assignment_blocks(source: str, name: str) -> set[str]:
    tree = ast.parse(source)
    for node in tree.body:
        if _is_assignment_to(node, name):
            return _block_names(ast.get_source_segment(source, node.value) or "")
    raise AssertionError(f"Missing Python assignment {name}")


def _is_assignment_to(node: ast.stmt, name: str) -> TypeGuard[ast.Assign]:
    return isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == name for target in node.targets
    )


def _ts_interface_fields(source: str) -> dict[str, dict[str, TsField]]:
    fields: dict[str, dict[str, TsField]] = {}
    for name in MIRRORED_MODELS:
        body = _ts_declaration_body(source, "interface", name)
        fields[name] = {}
        for line in body.splitlines():
            match = re.match(
                r"\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?P<optional>\?)?:\s*"
                r"(?P<type>.*);\s*$",
                line,
            )
            if match is None:
                continue
            fields[name][match.group("name")] = TsField(
                type=_normalize_ts_type(match.group("type")),
                optional=bool(match.group("optional")),
            )
    return fields


def _ts_type_values(source: str, name: str) -> list[str]:
    return re.findall(r'"([^"]+)"', _ts_declaration_body(source, "type", name))


def _ts_type_blocks(source: str, name: str) -> set[str]:
    return _block_names(_ts_declaration_body(source, "type", name))


def _ts_declaration_body(source: str, kind: str, name: str) -> str:
    if kind == "interface":
        pattern = rf"export interface {name}\s*{{(?P<body>.*?)\n}}"
    else:
        pattern = rf"export type {name}\s*=\s*(?P<body>.*?);"
    match = re.search(pattern, source, re.S)
    if match is None:
        raise AssertionError(f"Missing TypeScript {kind} {name}")
    return match.group("body")


def _field(
    fields: dict[str, dict[str, TsField]],
    model_name: str,
    field_name: str,
) -> TsField:
    try:
        return fields[model_name][field_name]
    except KeyError as error:
        raise AssertionError(f"Missing {model_name}.{field_name}") from error


def _field_blocks(
    fields: dict[str, dict[str, TsField]],
    model_name: str,
    field_name: str,
) -> set[str]:
    return _block_names(_field(fields, model_name, field_name).type)


def _block_names(source: str) -> set[str]:
    return set(re.findall(r"\b[A-Z][A-Za-z]+Block\b", source)) & BLOCK_MODELS


def _normalize_ts_type(source: str) -> str:
    return re.sub(r"\s+", " ", source.strip())
