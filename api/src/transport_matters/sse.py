"""Shared helpers for Server Sent Events payload decoding."""

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator


def iter_sse_data_objects(raw_body: bytes) -> Iterator[dict[str, Any]]:
    for line in raw_body.decode(errors="replace").splitlines():
        if not line.startswith("data:"):
            continue
        body = line[5:].strip()
        if body in ("", "[DONE]"):
            continue
        try:
            payload: Any = json.loads(body)  # Any: untyped SSE JSON
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            yield payload
