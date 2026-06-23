"""Restrictive file IO helpers for managed homes."""

from __future__ import annotations

import contextlib
import json
import os
from typing import (
    TYPE_CHECKING,
    Any,
)  # Any: JSON values carry driver supplied scalar and object types.

from transport_matters.atomic_io import write_atomic_bytes, write_atomic_json

from . import home_constants

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "write_atomic_json",
]


def _read_json_object_if_exists(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _copy_secret_file_if_missing(source: Path, target: Path) -> None:
    try:
        body = source.read_bytes()
    except FileNotFoundError:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            home_constants._JSON_FILE_MODE,
        )
    except FileExistsError:
        return

    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        target.chmod(home_constants._JSON_FILE_MODE)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            target.unlink()
        raise


def _write_atomic_secret(path: Path, body: bytes) -> None:
    write_atomic_bytes(path, body, mode=home_constants._JSON_FILE_MODE)
