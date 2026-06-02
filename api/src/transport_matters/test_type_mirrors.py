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

NON_BLOCK_MIRRORED_MODELS = (
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
OPTIONAL_MIRRORED_FIELDS = frozenset(
    (
        *((model_name, "provider_data") for model_name in NULLABLE_PROVIDER_MODELS),
        ("SystemPart", "cache_hint"),
    )
)


@dataclass(frozen=True)
class TsField:
    type: str
    optional: bool


def test_override_kind_values_match() -> None:
    py_values = _py_literal_values(PY_OVERRIDES.read_text(), "OverrideKind")
    ts_values = _ts_type_values(TS_TYPES.read_text(), "OverrideKind")

    assert set(ts_values) == set(py_values)


def test_ir_model_field_sets_match() -> None:
    py_source = PY_IR.read_text()
    mirrored_models = _mirrored_model_names(py_source)
    py_fields = _py_model_fields(py_source, mirrored_models)
    ts_fields = _ts_interface_fields(TS_TYPES.read_text(), mirrored_models)

    for model_name in mirrored_models:
        assert set(ts_fields[model_name]) == set(py_fields[model_name]), model_name
        assert _canonical_ts_fields(ts_fields[model_name]) == _canonical_py_fields(
            py_fields[model_name]
        ), model_name


def test_content_block_union_matches_python_ir() -> None:
    py_blocks = _py_assignment_blocks(PY_IR.read_text(), "ContentBlock")
    ts_blocks = _ts_type_blocks(TS_TYPES.read_text(), "ContentBlock")

    assert ts_blocks == py_blocks


def test_targeted_type_mirror_contracts() -> None:
    py_source = PY_IR.read_text()
    mirrored_models = _mirrored_model_names(py_source)
    py_fields = _py_model_fields(py_source, mirrored_models)
    ts_fields = _ts_interface_fields(TS_TYPES.read_text(), mirrored_models)

    assert _field(ts_fields, "Message", "role").type == "string"
    assert "provider_data" not in ts_fields["UnknownBlock"]

    for model_name, field_name in OPTIONAL_MIRRORED_FIELDS:
        field = _field(ts_fields, model_name, field_name)
        assert field == TsField(type=NULLABLE_RECORD, optional=True)
    assert _field_blocks(ts_fields, "ToolResultBlock", "content") == _py_field_blocks(
        py_fields,
        "ToolResultBlock",
        "content",
    )
    assert _field_blocks(ts_fields, "InternalResponse", "content") == _py_field_blocks(
        py_fields,
        "InternalResponse",
        "content",
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


def _mirrored_model_names(source: str) -> tuple[str, ...]:
    return (
        *_py_assignment_block_sequence(source, "ContentBlock"),
        *NON_BLOCK_MIRRORED_MODELS,
    )


def _py_model_fields(
    source: str,
    model_names: tuple[str, ...],
) -> dict[str, dict[str, str]]:
    tree = ast.parse(source)
    fields: dict[str, dict[str, str]] = {}
    model_set = set(model_names)
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name not in model_set:
            continue
        fields[node.name] = {
            statement.target.id: ast.get_source_segment(source, statement.annotation) or ""
            for statement in node.body
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
        }
    return fields


def _py_assignment_blocks(source: str, name: str) -> set[str]:
    return set(_py_assignment_block_sequence(source, name))


def _py_assignment_block_sequence(source: str, name: str) -> tuple[str, ...]:
    tree = ast.parse(source)
    for node in tree.body:
        if _is_assignment_to(node, name):
            return _block_name_sequence(ast.get_source_segment(source, node.value) or "")
    raise AssertionError(f"Missing Python assignment {name}")


def _is_assignment_to(node: ast.stmt, name: str) -> TypeGuard[ast.Assign]:
    return isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == name for target in node.targets
    )


def _ts_interface_fields(
    source: str,
    model_names: tuple[str, ...],
) -> dict[str, dict[str, TsField]]:
    fields: dict[str, dict[str, TsField]] = {}
    for name in model_names:
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


def _py_field_blocks(
    fields: dict[str, dict[str, str]],
    model_name: str,
    field_name: str,
) -> set[str]:
    try:
        return _block_names(fields[model_name][field_name])
    except KeyError as error:
        raise AssertionError(f"Missing Python {model_name}.{field_name}") from error


def _block_names(source: str) -> set[str]:
    return set(_block_name_sequence(source))


def _block_name_sequence(source: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(re.findall(r"\b[A-Z][A-Za-z]+Block\b", source)))


def _normalize_ts_type(source: str) -> str:
    return re.sub(r"\s+", " ", source.strip())


def _canonical_py_fields(
    fields: dict[str, str],
) -> dict[str, str]:
    return {field_name: _canonical_py_type(field_type) for field_name, field_type in fields.items()}


def _canonical_ts_fields(
    fields: dict[str, TsField],
) -> dict[str, str]:
    return {field_name: _canonical_ts_type(field.type) for field_name, field in fields.items()}


def _canonical_ts_type(source: str) -> str:
    normalized = re.sub(r"\s+", " ", source.strip())
    union_members = _split_top_level_union(normalized)
    if len(union_members) > 1:
        return " | ".join(_canonical_ts_type(member) for member in union_members)

    array_short_match = re.fullmatch(r"(?P<inner>[A-Za-z_][A-Za-z0-9_]*)\[\]", normalized)
    if array_short_match is not None:
        return f"Array<{_canonical_ts_type(array_short_match.group('inner'))}>"

    array_match = re.fullmatch(r"Array<(?P<inner>.*)>", normalized)
    if array_match is not None:
        return f"Array<{_canonical_ts_type(array_match.group('inner'))}>"

    record_match = re.fullmatch(r"Record<string, (?P<value>.*)>", normalized)
    if record_match is not None:
        return f"Record<string, {_canonical_ts_type(record_match.group('value'))}>"

    return normalized


def _canonical_py_type(source: str) -> str:
    source = re.sub(r"\s+", " ", source.strip())
    return " | ".join(
        _canonical_py_union_member(member) for member in _split_top_level_union(source)
    )


def _canonical_py_union_member(source: str) -> str:
    if source == "None":
        return "null"
    if source == "Any":
        return "unknown"

    literal_match = re.fullmatch(r'Literal\[(?P<value>"[^"]+")\]', source)
    if literal_match is not None:
        return literal_match.group("value")

    list_match = re.fullmatch(r"(?:list|Sequence)\[(?P<inner>.*)\]", source)
    if list_match is not None:
        return f"Array<{_canonical_py_type(list_match.group('inner'))}>"

    record_match = re.fullmatch(r"dict\[str, (?P<value>.*)\]", source)
    if record_match is not None:
        return f"Record<string, {_canonical_py_type(record_match.group('value'))}>"

    return {
        "str": "string",
        "bool": "boolean",
        "int": "number",
        "float": "number",
        "dict[str, Any]": "Record<string, unknown>",
    }.get(source, source)


def _split_top_level_union(source: str) -> list[str]:
    members: list[str] = []
    start = 0
    square_depth = 0
    angle_depth = 0

    for index, char in enumerate(source):
        if char == "[":
            square_depth += 1
        elif char == "]":
            square_depth -= 1
        elif char == "<":
            angle_depth += 1
        elif char == ">":
            angle_depth -= 1
        elif char == "|" and square_depth == 0 and angle_depth == 0:
            members.append(source[start:index].strip())
            start = index + 1

    members.append(source[start:].strip())
    return members
