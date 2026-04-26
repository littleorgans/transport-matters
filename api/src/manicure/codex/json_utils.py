"""Shared JSON canonicalization helpers for Codex artifacts."""

from __future__ import annotations

import json
from typing import Any


def canonicalize_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: canonicalize_json(nested_value)
            for key, nested_value in sorted(value.items())
        }
    if isinstance(value, list):
        return [canonicalize_json(item) for item in value]
    return value


def compact_json(value: object) -> str:
    return json.dumps(canonicalize_json(value), separators=(",", ":"))


def json_text_length(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return len(value)
    return len(compact_json(value))


__all__ = [
    "canonicalize_json",
    "compact_json",
    "json_text_length",
]
