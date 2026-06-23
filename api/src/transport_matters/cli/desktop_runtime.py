"""CLI compatibility exports for detached desktop runtime records."""

from __future__ import annotations

from transport_matters.desktop_runtime import (
    DesktopRuntimeDiscoveryError,
    DesktopRuntimeRecord,
    DesktopRuntimeState,
    DesktopRuntimeStatus,
    DesktopRuntimeStatusJson,
    DesktopRuntimeStatusResponseJson,
    RouteName,
    StopDesktopResult,
    desktop_log_path,
    desktop_record_path,
    desktop_runtime_dir,
    desktop_runtime_status_to_json,
    discover_desktop_runtime,
    is_pid_alive,
    read_live_desktop_record,
    stop_desktop_record,
    write_desktop_record,
)

__all__ = [
    "DesktopRuntimeDiscoveryError",
    "DesktopRuntimeRecord",
    "DesktopRuntimeState",
    "DesktopRuntimeStatus",
    "DesktopRuntimeStatusJson",
    "DesktopRuntimeStatusResponseJson",
    "RouteName",
    "StopDesktopResult",
    "desktop_log_path",
    "desktop_record_path",
    "desktop_runtime_dir",
    "desktop_runtime_status_to_json",
    "discover_desktop_runtime",
    "is_pid_alive",
    "read_live_desktop_record",
    "stop_desktop_record",
    "write_desktop_record",
]
