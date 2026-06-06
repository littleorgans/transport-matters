"""Shared low-level canonical-JSON helpers.

Extracted from ``override_audit.py`` so character accounting can share one copy
of the JSON-canonicalization discipline without duplicating it.

This module depends only on the standard library (DAG layer 1, beside ``ir``); it
imports nothing from ``transport_matters``.

``canonical_json`` / ``canonical_fields`` / ``json_string`` are public because they are
consumed across module boundaries; the module-privacy
boundary requires cross-module symbols to be public names. The number/mapping helpers
are intra-module and stay underscore-private.
"""

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any  # Any: embedded provider/tool JSON is schema-free

_EXPONENT_RE = re.compile(r"e([+-]?)(0*)(\d+)$")
_MAX_DECIMAL_INTEGER_FLOAT = 1e21


def json_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _canonical_exponent(value: str) -> str:
    return _EXPONENT_RE.sub(
        lambda match: f"e{'-' if match.group(1) == '-' else ''}{int(match.group(3))}",
        value.lower(),
    )


def _canonical_number(value: int | float) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        raise ValueError("non-finite numbers are not valid char-accounting JSON")
    if value.is_integer() and abs(value) < _MAX_DECIMAL_INTEGER_FLOAT:
        return str(int(value))
    # TypeScript mirrors Python's exponent threshold for small decimal floats.
    return _canonical_exponent(
        json.dumps(value, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
    )


def _canonical_mapping(value: Mapping[str, Any]) -> str:
    fields = []
    for key in value:
        if not isinstance(key, str):
            raise ValueError("char-accounting JSON object keys must be strings")
    for key in sorted(value):
        fields.append(f"{json_string(key)}:{canonical_json(value[key])}")
    return "{" + ",".join(fields) + "}"


def canonical_json(value: Any) -> str:  # Any: embedded IR dictionaries are schema-free
    """Return canonical compact JSON for embedded IR dictionaries."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json_string(value)
    if isinstance(value, int | float):
        return _canonical_number(value)
    if isinstance(value, Mapping):
        return _canonical_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return "[" + ",".join(canonical_json(item) for item in value) + "]"
    raise TypeError(f"Unsupported char-accounting JSON value: {type(value).__name__}")


def canonical_fields(fields: Sequence[tuple[str, str]]) -> str:
    """Join ``(key, already-canonical-value)`` pairs into an object, order preserved.

    Keys are JSON-escaped; values are emitted verbatim. The caller owns field order
    (the type-first identity discipline lives in the higher-level encoders).
    """
    return "{" + ",".join(f"{json_string(key)}:{value}" for key, value in fields) + "}"
