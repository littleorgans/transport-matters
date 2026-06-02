"""Private target parsing and index adjustment helpers for overrides."""

import re

_INDEX_RE = re.compile(r"^(0|-?[1-9][0-9]*)$")


def tool_target(name: str) -> str:
    return f"tool:{name}"


def system_target(index: int) -> str:
    return f"system:{index}"


def tool_result_target(tool_use_id: str) -> str:
    return f"toolresult:{tool_use_id}"


def sampling_target(field: str) -> str:
    return f"sampling:{field}"


def provider_extras_target(key: str) -> str:
    return f"provider_extras:{key}"


def message_block_target(msg_idx: int, blk_idx: int) -> str:
    return f"msg:{msg_idx}:blk:{blk_idx}"


def parse_prefixed(target: str, prefix: str) -> str | None:
    """Extract the value after ``prefix`` if ``target`` starts with it."""
    if target.startswith(prefix):
        return target[len(prefix) :]
    return None


def parse_prefixed_int(target: str, prefix: str) -> int | None:
    """Extract an integer value after ``prefix``."""
    raw = parse_prefixed(target, prefix)
    if raw is None or _INDEX_RE.fullmatch(raw) is None:
        return None
    return int(raw)


def parse_tool_name(target: str) -> str | None:
    """Extract tool name from ``tool:{name}``."""
    return parse_prefixed(target, "tool:")


def parse_system_index(target: str) -> int | None:
    """Extract index from ``system:{index}``."""
    return parse_prefixed_int(target, "system:")


def parse_tool_result_id(target: str) -> str | None:
    """Extract tool_use_id from ``toolresult:{id}``."""
    return parse_prefixed(target, "toolresult:")


def parse_sampling_field(target: str) -> str | None:
    """Extract field name from ``sampling:{field}``."""
    return parse_prefixed(target, "sampling:")


def parse_provider_extras_key(target: str) -> str | None:
    """Extract key from ``provider_extras:{key}``."""
    return parse_prefixed(target, "provider_extras:")


def parse_message_target(target: str) -> tuple[int, int] | None:
    """Extract (msg_idx, blk_idx) from ``msg:{idx}:blk:{idx}``."""
    parts = target.split(":")
    if len(parts) != 4 or parts[0] != "msg" or parts[2] != "blk":
        return None
    if _INDEX_RE.fullmatch(parts[1]) is None or _INDEX_RE.fullmatch(parts[3]) is None:
        return None
    return int(parts[1]), int(parts[3])


def adjust_system_index(original_index: int, removed_indices: set[int]) -> int:
    """Map an original system index to its current position after removals."""
    return _shift_after_removals(original_index, removed_indices)


def _shift_after_removals(index: int, removed: set[int]) -> int:
    return index - sum(1 for prior in removed if prior < index)


def adjust_blk_index(
    msg_idx: int, original_blk_idx: int, removed_blk_indices: dict[int, set[int]]
) -> int | None:
    """Map an original block index to its current position after earlier removals.

    Only ``message_block_toggle`` mutates the block layout during the
    apply pipeline, so the shift map is built up as each toggle runs.
    Returns ``None`` if the target block itself was already removed.
    """
    removed = removed_blk_indices.get(msg_idx, set())
    if original_blk_idx in removed:
        return None
    return _shift_after_removals(original_blk_idx, removed)
