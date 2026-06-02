"""Private metadata mutation helpers for overrides."""

import copy
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from transport_matters.ir import InternalRequest

SAMPLING_FIELDS = frozenset({"max_tokens", "temperature", "top_p", "top_k", "stop_sequences"})


def sampling_value_valid(field: str, value: object) -> bool:
    """Shape-check a parsed sampling value against the field's expected type.

    Values arrive JSON-decoded. bool is a subclass of int in Python, so the
    isinstance checks reject True/False for numeric fields explicitly.
    """
    if field == "max_tokens":
        return isinstance(value, int) and not isinstance(value, bool) and value >= 1
    if field in {"temperature", "top_p"}:
        if value is None:
            return True
        if isinstance(value, bool):
            return False
        return isinstance(value, (int, float))
    if field == "top_k":
        if value is None:
            return True
        return isinstance(value, int) and not isinstance(value, bool)
    if field == "stop_sequences":
        return isinstance(value, list) and all(isinstance(item, str) for item in value)
    return False


def apply_sampling_set(
    ir: InternalRequest, field: str, value: object
) -> tuple[InternalRequest, int, bool]:
    """Set a field on ir.sampling to a parsed value. chars_delta is always 0."""
    if field not in SAMPLING_FIELDS:
        return ir, 0, False
    if not sampling_value_valid(field, value):
        return ir, 0, False
    new_sampling = ir.sampling.model_copy(update={field: value})
    return ir.model_copy(update={"sampling": new_sampling}), 0, True


def is_forbidden_segment(segment: str) -> bool:
    """Reject path segments that could enable attribute-style escapes."""
    if segment == "constructor":
        return True
    return segment.startswith("__") and segment.endswith("__") and len(segment) >= 4


def set_nested_path(node: dict[str, Any], path: list[str], value: Any) -> bool:
    """Traverse ``path`` creating empty-dict intermediates as needed, set leaf."""
    for segment in path[:-1]:
        if segment not in node:
            node[segment] = {}
        elif not isinstance(node[segment], dict):
            return False
        node = node[segment]
    node[path[-1]] = value
    return True


def delete_nested_path(root: dict[str, Any], path: list[str]) -> bool:
    """Delete the leaf and recursively prune empty-dict parents."""
    chain: list[tuple[dict[str, Any], str]] = []
    node = root
    for segment in path[:-1]:
        if segment not in node:
            return True
        if not isinstance(node[segment], dict):
            return False
        chain.append((node, segment))
        node = node[segment]
    node.pop(path[-1], None)
    for parent, parent_key in reversed(chain):
        if not parent[parent_key]:
            del parent[parent_key]
    return True


def apply_provider_extras_set(
    ir: InternalRequest, key: str, value: object
) -> tuple[InternalRequest, int, bool]:
    """Set a dotted path in ``ir.provider_extras`` to a parsed value."""
    if not key:
        return ir, 0, False
    path = key.split(".")
    if any(not segment or is_forbidden_segment(segment) for segment in path):
        return ir, 0, False

    new_extras = copy.deepcopy(dict(ir.provider_extras))

    if value is None:
        if not delete_nested_path(new_extras, path):
            return ir, 0, False
    else:
        if not set_nested_path(new_extras, path, value):
            return ir, 0, False

    return ir.model_copy(update={"provider_extras": new_extras}), 0, True
