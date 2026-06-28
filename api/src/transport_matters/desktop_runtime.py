"""Runtime record helpers for detached desktop backends."""

from __future__ import annotations

import contextlib
import errno
import json
import os
import signal
import socket
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict

from transport_matters.atomic_io import write_atomic_json
from transport_matters.desktop_event import build_backend_started_event
from transport_matters.loopback import loopback_http_url

if TYPE_CHECKING:
    from collections.abc import Callable

_SCHEMA_VERSION: Literal[2] = 2
_LEGACY_SCHEMA_VERSION: Literal[1] = 1
_DEFAULT_INSTANCE = "channel"
_RUNTIME_DIRNAME = "runtime"
_RECORD_FILENAME = "desktop.json"
_LOG_FILENAME = "desktop.log"
_FIELD_ALIASES = {
    "schema_version": "schemaVersion",
    "proxy_port": "proxyPort",
    "web_port": "webPort",
    "storage_dir": "storageDir",
    "log_path": "logPath",
    "started_at": "startedAt",
}

DesktopRuntimeState = Literal["absent", "live", "stale", "unhealthy", "not-serving", "wedged"]
RouteName = Literal["canvas", "canvas-lab"]
DesktopHealthProbeStatus = Literal["live", "refused", "timeout", "failed"]


class DesktopRuntimeStatusJson(TypedDict):
    schemaVersion: Literal[2]
    state: DesktopRuntimeState
    channel: str
    instance: str
    pid: int | None
    proxyPort: int | None
    webPort: int | None
    apiBaseUrl: str | None
    healthUrl: str | None
    defaultRouteUrl: str | None
    cwd: str | None
    storageDir: str
    recordPath: str
    logPath: str | None
    startedAt: str | None
    version: str | None
    reason: NotRequired[str]


class DesktopRuntimeStatusResponseJson(TypedDict):
    runtime: DesktopRuntimeStatusJson


@dataclass(frozen=True, slots=True)
class DesktopLivenessPolicy:
    attempts: int = 3
    per_probe_timeout_s: float = 2.0
    backoff_s: float = 0.2


@dataclass(frozen=True, slots=True)
class DesktopHealthProbeResult:
    status: DesktopHealthProbeStatus
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DesktopRuntimeLiveMeta:
    channel: str | None
    cwd: str | None


@dataclass(frozen=True, slots=True)
class DesktopRuntimeRecord:
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    channel: str
    pid: int
    proxy_port: int
    web_port: int
    log_path: str
    cwd: str | None = None
    storage_dir: str | None = None
    version: str | None = None
    instance: str = _DEFAULT_INSTANCE
    started_at: str = field(
        default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    )


@dataclass(frozen=True, slots=True)
class DesktopRuntimeStatus:
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    state: DesktopRuntimeState
    channel: str
    instance: str
    pid: int | None
    proxy_port: int | None
    web_port: int | None
    api_base_url: str | None
    health_url: str | None
    default_route_url: str | None
    cwd: str | None
    storage_dir: str
    record_path: str
    log_path: str | None
    started_at: str | None
    version: str | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class StopDesktopResult:
    status: Literal["nothing", "stopped"]
    pid: int | None = None


class DesktopRuntimeDiscoveryError(RuntimeError):
    code: Literal["desktop_runtime_unavailable", "desktop_runtime_invalid"]
    message: str
    details: dict[str, object] | None

    def __init__(
        self,
        *,
        code: Literal["desktop_runtime_unavailable", "desktop_runtime_invalid"],
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def desktop_runtime_dir(storage_dir: Path) -> Path:
    return storage_dir / _RUNTIME_DIRNAME


def desktop_record_path(storage_dir: Path) -> Path:
    return desktop_runtime_dir(storage_dir) / _RECORD_FILENAME


def desktop_log_path(storage_dir: Path) -> Path:
    return desktop_runtime_dir(storage_dir) / _LOG_FILENAME


def write_desktop_record(record_path: Path, record: DesktopRuntimeRecord) -> None:
    write_atomic_json(record_path, asdict(record))


def probe_desktop_liveness(
    web_port: int,
    *,
    policy: DesktopLivenessPolicy | None = None,
    probe_once: Callable[..., DesktopHealthProbeResult] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> DesktopHealthProbeResult:
    resolved = policy or DesktopLivenessPolicy()
    attempts = max(resolved.attempts, 1)
    timeout_s = max(resolved.per_probe_timeout_s, 0.05)
    probe = probe_once or _probe_desktop_health
    sleep_func = sleep or time.sleep
    results: list[DesktopHealthProbeResult] = []
    for index in range(attempts):
        result = probe(web_port, timeout_s=timeout_s)
        if result.status == "live":
            return result
        results.append(result)
        if index < attempts - 1 and resolved.backoff_s > 0:
            sleep_func(resolved.backoff_s)
    if any(result.status == "timeout" for result in results):
        return DesktopHealthProbeResult(status="timeout")
    if results and all(result.status == "refused" for result in results):
        return DesktopHealthProbeResult(status="refused")
    return DesktopHealthProbeResult(status="failed")


def discover_desktop_runtime(
    *,
    channel: str,
    storage_dir: Path,
    route: RouteName,
    cwd: Path,
    health_timeout_ms: int | None = None,
    liveness_policy: DesktopLivenessPolicy | None = None,
) -> DesktopRuntimeStatus:
    """Return the runtime status for a channel without starting a backend."""
    resolved_storage = storage_dir.expanduser().resolve()
    resolved_cwd = cwd.expanduser().resolve()
    record_path = desktop_record_path(resolved_storage)
    record, invalid_reason = _read_record_for_discovery(record_path)
    if record is None:
        state: DesktopRuntimeState = "stale" if invalid_reason is not None else "absent"
        return _status_without_record(
            state=state,
            channel=channel,
            storage_dir=resolved_storage,
            record_path=record_path,
            reason=invalid_reason,
        )

    status = _status_from_record(
        record,
        state="unhealthy" if record.channel != channel else "stale",
        storage_dir=resolved_storage,
        record_path=record_path,
        route=route,
        cwd=resolved_cwd,
        reason="record_channel_mismatch" if record.channel != channel else "pid_not_running",
    )
    if record.channel != channel:
        return status

    try:
        pid_is_alive = is_pid_alive(record.pid)
    except OSError:
        return _status_from_record(
            record,
            state="unhealthy",
            storage_dir=resolved_storage,
            record_path=record_path,
            route=route,
            cwd=resolved_cwd,
            reason="pid_probe_failed",
        )

    if not pid_is_alive:
        _unlink_desktop_record(record_path, ignore_permission=True)
        return status

    policy = _resolve_liveness_policy(liveness_policy, health_timeout_ms)
    liveness = probe_desktop_liveness(record.web_port, policy=policy)
    if liveness.status != "live":
        state, reason = _status_for_probe_result(liveness)
        return _status_from_record(
            record,
            state=state,
            storage_dir=resolved_storage,
            record_path=record_path,
            route=route,
            cwd=resolved_cwd,
            reason=reason,
        )

    meta = _read_runtime_meta(record.web_port, timeout_s=policy.per_probe_timeout_s)
    if meta is not None and meta.channel is not None and meta.channel != channel:
        return _status_from_record(
            record,
            state="unhealthy",
            storage_dir=resolved_storage,
            record_path=record_path,
            route=route,
            cwd=resolved_cwd,
            reason="channel_mismatch",
        )
    live_cwd: Path | None = None
    if meta is not None and meta.cwd is not None:
        live_cwd = Path(meta.cwd).expanduser().resolve()

    return _status_from_record(
        record,
        state="live",
        storage_dir=resolved_storage,
        record_path=record_path,
        route=route,
        cwd=resolved_cwd,
        reason=None,
        live_cwd=live_cwd,
    )


def desktop_runtime_status_to_json(
    status: DesktopRuntimeStatus,
) -> DesktopRuntimeStatusResponseJson:
    runtime: DesktopRuntimeStatusJson = {
        "schemaVersion": _SCHEMA_VERSION,
        "state": status.state,
        "channel": status.channel,
        "instance": status.instance,
        "pid": status.pid,
        "proxyPort": status.proxy_port,
        "webPort": status.web_port,
        "apiBaseUrl": status.api_base_url,
        "healthUrl": status.health_url,
        "defaultRouteUrl": status.default_route_url,
        "cwd": status.cwd,
        "storageDir": status.storage_dir,
        "recordPath": status.record_path,
        "logPath": status.log_path,
        "startedAt": status.started_at,
        "version": status.version,
    }
    if status.reason is not None:
        runtime["reason"] = status.reason
    return {"runtime": runtime}


def _resolve_liveness_policy(
    policy: DesktopLivenessPolicy | None,
    health_timeout_ms: int | None,
) -> DesktopLivenessPolicy:
    if policy is not None:
        return policy
    if health_timeout_ms is None:
        return DesktopLivenessPolicy()
    return DesktopLivenessPolicy(per_probe_timeout_s=max(health_timeout_ms, 0) / 1000.0)


def _status_for_probe_result(
    result: DesktopHealthProbeResult,
) -> tuple[DesktopRuntimeState, str]:
    if result.status == "refused":
        return "not-serving", "health_probe_refused"
    if result.status == "timeout":
        return "wedged", "health_probe_timeout"
    return "unhealthy", "health_probe_failed"


def _probe_desktop_health(web_port: int, *, timeout_s: float) -> DesktopHealthProbeResult:
    url = f"{loopback_http_url(web_port)}/health"
    try:
        with urllib.request.urlopen(url, timeout=max(timeout_s, 0.05)) as response:
            status = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        return DesktopHealthProbeResult(status="failed", reason=f"http_{exc.code}")
    except urllib.error.URLError as exc:
        reason = exc.reason
        if _is_connection_refused(reason):
            return DesktopHealthProbeResult(status="refused")
        if _is_timeout_error(reason):
            return DesktopHealthProbeResult(status="timeout")
        return DesktopHealthProbeResult(status="failed", reason=str(reason))
    except TimeoutError:
        return DesktopHealthProbeResult(status="timeout")
    except OSError as exc:
        if _is_connection_refused(exc):
            return DesktopHealthProbeResult(status="refused")
        if _is_timeout_error(exc):
            return DesktopHealthProbeResult(status="timeout")
        return DesktopHealthProbeResult(status="failed", reason=str(exc))
    return DesktopHealthProbeResult(status="live" if 200 <= status < 300 else "failed")


def _is_connection_refused(value: object) -> bool:
    return isinstance(value, ConnectionRefusedError) or (
        isinstance(value, OSError) and value.errno == errno.ECONNREFUSED
    )


def _is_timeout_error(value: object) -> bool:
    return isinstance(value, TimeoutError | socket.timeout) or (
        isinstance(value, OSError) and value.errno == errno.ETIMEDOUT
    )


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

    _unlink_desktop_record(record_path, ignore_permission=True)
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


def stop_desktop_record(
    record_path: Path,
    *,
    timeout_s: float = 3.0,
    poll_s: float = 0.1,
    pid_alive: Callable[[int], bool] | None = None,
    kill: Callable[[int, int], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> StopDesktopResult:
    pid_alive_func = pid_alive or is_pid_alive
    kill_func = kill or os.kill
    record = _read_desktop_record_for_stop(record_path)
    if record is None:
        return StopDesktopResult(status="nothing")

    if not pid_alive_func(record.pid):
        _unlink_desktop_record(record_path)
        return StopDesktopResult(status="nothing")

    try:
        kill_func(record.pid, signal.SIGTERM)
    except ProcessLookupError:
        _unlink_desktop_record(record_path)
        return StopDesktopResult(status="stopped", pid=record.pid)

    remaining_s = max(timeout_s, 0.0)
    interval_s = poll_s if poll_s > 0 else remaining_s
    while remaining_s > 0:
        if not pid_alive_func(record.pid):
            _unlink_desktop_record(record_path)
            return StopDesktopResult(status="stopped", pid=record.pid)
        sleep_for_s = min(interval_s, remaining_s)
        sleep(sleep_for_s)
        remaining_s -= sleep_for_s

    if not pid_alive_func(record.pid):
        _unlink_desktop_record(record_path)
        return StopDesktopResult(status="stopped", pid=record.pid)

    with contextlib.suppress(ProcessLookupError):
        kill_func(record.pid, signal.SIGKILL)
    _unlink_desktop_record(record_path)
    return StopDesktopResult(status="stopped", pid=record.pid)


def _read_desktop_record_for_stop(record_path: Path) -> DesktopRuntimeRecord | None:
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        return _record_from_payload(payload)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError, TypeError, ValueError:
        _unlink_desktop_record(record_path)
        return None


def _unlink_desktop_record(record_path: Path, *, ignore_permission: bool = False) -> None:
    ignored_errors = (
        (FileNotFoundError, PermissionError) if ignore_permission else (FileNotFoundError,)
    )
    with contextlib.suppress(*ignored_errors):
        record_path.unlink()


def _record_from_payload(payload: Any) -> DesktopRuntimeRecord:
    if not isinstance(payload, dict):
        raise ValueError("desktop runtime record must be an object")
    schema_version = _require_int(payload, "schema_version")
    if schema_version not in {_LEGACY_SCHEMA_VERSION, _SCHEMA_VERSION}:
        raise ValueError(f"unsupported desktop runtime schema {schema_version}")
    cwd = _optional_str(payload, "cwd")
    storage_dir = _optional_str(payload, "storage_dir")
    version = _optional_str(payload, "version")
    if schema_version == _SCHEMA_VERSION:
        cwd = _require_str(payload, "cwd")
        storage_dir = _require_str(payload, "storage_dir")
        version = _require_str(payload, "version")
    return DesktopRuntimeRecord(
        channel=_require_str(payload, "channel"),
        pid=_require_positive_int(payload, "pid"),
        proxy_port=_require_positive_int(payload, "proxy_port"),
        web_port=_require_positive_int(payload, "web_port"),
        log_path=_require_str(payload, "log_path"),
        cwd=cwd,
        storage_dir=storage_dir,
        version=version,
        instance=_optional_str(payload, "instance") or _DEFAULT_INSTANCE,
        started_at=_require_str(payload, "started_at"),
    )


def _require_str(payload: dict[str, Any], key: str) -> str:
    value = _payload_value(payload, key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"desktop runtime {key} must be a non-empty string")
    return value


def _require_int(payload: dict[str, Any], key: str) -> int:
    value = _payload_value(payload, key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"desktop runtime {key} must be an integer")
    return value


def _require_positive_int(payload: dict[str, Any], key: str) -> int:
    value = _require_int(payload, key)
    if value <= 0:
        raise ValueError(f"desktop runtime {key} must be positive")
    return value


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = _payload_value(payload, key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"desktop runtime {key} must be a non-empty string")
    return value


def _payload_value(payload: dict[str, Any], key: str) -> Any:
    if key in payload:
        return payload[key]
    alias = _FIELD_ALIASES.get(key)
    if alias is not None and alias in payload:
        return payload[alias]
    return None


def _read_record_for_discovery(
    record_path: Path,
) -> tuple[DesktopRuntimeRecord | None, str | None]:
    try:
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        return _record_from_payload(payload), None
    except FileNotFoundError:
        return None, None
    except PermissionError as exc:
        raise DesktopRuntimeDiscoveryError(
            code="desktop_runtime_unavailable",
            message=f"desktop runtime record is not readable: {record_path}",
            details={"recordPath": str(record_path), "error": str(exc)},
        ) from exc
    except json.JSONDecodeError as exc:
        _unlink_desktop_record(record_path, ignore_permission=True)
        raise DesktopRuntimeDiscoveryError(
            code="desktop_runtime_invalid",
            message=f"desktop runtime record is invalid: {record_path}",
            details={"recordPath": str(record_path), "reason": "invalid_json", "error": str(exc)},
        ) from exc
    except (TypeError, ValueError) as exc:
        _unlink_desktop_record(record_path, ignore_permission=True)
        raise DesktopRuntimeDiscoveryError(
            code="desktop_runtime_invalid",
            message=f"desktop runtime record is invalid: {record_path}",
            details={"recordPath": str(record_path), "reason": "invalid_record", "error": str(exc)},
        ) from exc


def _status_without_record(
    *,
    state: DesktopRuntimeState,
    channel: str,
    storage_dir: Path,
    record_path: Path,
    reason: str | None,
) -> DesktopRuntimeStatus:
    return DesktopRuntimeStatus(
        state=state,
        channel=channel,
        instance=_DEFAULT_INSTANCE,
        pid=None,
        proxy_port=None,
        web_port=None,
        api_base_url=None,
        health_url=None,
        default_route_url=None,
        cwd=None,
        storage_dir=str(storage_dir),
        record_path=str(record_path),
        log_path=None,
        started_at=None,
        version=None,
        reason=reason,
    )


def _status_from_record(
    record: DesktopRuntimeRecord,
    *,
    state: DesktopRuntimeState,
    storage_dir: Path,
    record_path: Path,
    route: RouteName,
    cwd: Path,
    reason: str | None,
    live_cwd: Path | None = None,
) -> DesktopRuntimeStatus:
    if live_cwd is not None:
        runtime_cwd = live_cwd
    elif record.cwd is not None:
        runtime_cwd = Path(record.cwd).expanduser().resolve()
    else:
        runtime_cwd = cwd
    runtime_storage = (
        Path(record.storage_dir).expanduser().resolve()
        if record.storage_dir is not None
        else storage_dir
    )
    api_base_url = loopback_http_url(record.web_port)
    event = build_backend_started_event(
        route=route,
        cwd=runtime_cwd,
        resolved_storage=runtime_storage,
        web_port=record.web_port,
    )
    return DesktopRuntimeStatus(
        state=state,
        channel=record.channel,
        instance=record.instance,
        pid=record.pid,
        proxy_port=record.proxy_port,
        web_port=record.web_port,
        api_base_url=api_base_url,
        health_url=f"{api_base_url}/health",
        default_route_url=str(event["routeUrl"]),
        cwd=str(runtime_cwd),
        storage_dir=str(runtime_storage),
        record_path=str(record_path),
        log_path=record.log_path,
        started_at=record.started_at,
        version=record.version,
        reason=reason,
    )


def _read_runtime_meta(web_port: int, *, timeout_s: float) -> DesktopRuntimeLiveMeta | None:
    url = f"{loopback_http_url(web_port)}/api/meta"
    try:
        with urllib.request.urlopen(url, timeout=max(timeout_s, 0.05)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    channel = payload.get("channel")
    cwd = payload.get("cwd")
    return DesktopRuntimeLiveMeta(
        channel=channel if isinstance(channel, str) else None,
        cwd=cwd if isinstance(cwd, str) else None,
    )
