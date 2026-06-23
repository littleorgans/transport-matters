"""Small atomic file write helpers shared across runtime layers."""

from __future__ import annotations

import contextlib
import json
import os
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from pathlib import Path


def write_atomic_json(path: Path, value: dict[str, Any]) -> None:
    body = json.dumps(value, indent=2).encode("utf-8") + b"\n"
    write_atomic_bytes(path, body)


def write_atomic_bytes(path: Path, body: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        temp.chmod(mode)
        temp.replace(path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()
