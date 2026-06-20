"""Runtime record helpers for detached desktop backends."""

from __future__ import annotations

import contextlib
import errno
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .home_io import write_atomic_json

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_SCHEMA_VERSION = 1
_RUNTIME_DIRNAME = "runtime"
_RECORD_FILENAME = "desktop.json"
_LOG_FILENAME = "desktop.log"


@dataclass(frozen=True, slots=True)
class DesktopRuntimeRecord:
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    channel: str
    pid: int
    proxy_port: int
    web_port: int
    log_path: str
    started_at: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def desktop_runtime_dir(storage_dir: Path) -> Path:
    return storage_dir / _RUNTIME_DIRNAME


def desktop_record_path(storage_dir: Path) -> Path:
    return desktop_runtime_dir(storage_dir) / _RECORD_FILENAME


def desktop_log_path(storage_dir: Path) -> Path:
    return desktop_runtime_dir(storage_dir) / _LOG_FILENAME


def write_desktop_record(record_path: Path, record: DesktopRuntimeRecord) -> None:
    write_atomic_json(record_path, asdict(record))


def read_live_desktop_record(
    record_path: Path,
    *,
    pid_alive: Callable[[int], bool] | None = None,
) -> DesktopRuntimeRecord | None:
    check_alive = is_pid_alive if pid_alive is None else pid_alive
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        record = _record_from_payload(payload)
        alive = check_alive(record.pid)
    except FileNotFoundError, PermissionError, json.JSONDecodeError, TypeError, ValueError:
        return None

    if alive:
        return record

    with contextlib.suppress(FileNotFoundError, PermissionError):
        record_path.unlink()
    return None


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno in {errno.ESRCH, errno.EPERM}:
            return False
        raise
    return True


def _record_from_payload(payload: Any) -> DesktopRuntimeRecord:
    if not isinstance(payload, dict):
        raise ValueError("desktop runtime record must be an object")
    schema_version = _require_int(payload, "schema_version")
    if schema_version != _SCHEMA_VERSION:
        raise ValueError(f"unsupported desktop runtime schema {schema_version}")
    return DesktopRuntimeRecord(
        channel=_require_str(payload, "channel"),
        pid=_require_positive_int(payload, "pid"),
        proxy_port=_require_positive_int(payload, "proxy_port"),
        web_port=_require_positive_int(payload, "web_port"),
        log_path=_require_str(payload, "log_path"),
        started_at=_require_str(payload, "started_at"),
    )


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"desktop runtime {key} must be a non-empty string")
    return value


def _require_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"desktop runtime {key} must be an integer")
    return value


def _require_positive_int(payload: dict[str, Any], key: str) -> int:
    value = _require_int(payload, key)
    if value <= 0:
        raise ValueError(f"desktop runtime {key} must be positive")
    return value
