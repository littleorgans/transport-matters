"""Desktop runtime recovery and refusal policy."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer

from .desktop_runtime import (
    DesktopLivenessPolicy,
    DesktopRuntimeDiscoveryError,
    DesktopRuntimeStatus,
    RouteName,
    discover_desktop_runtime,
    stop_desktop_record,
)


def prepare_desktop_runtime_for_launch_or_exit(
    *,
    channel: str,
    storage_dir: Path,
    route: RouteName,
    cwd: Path,
    force_restart: bool = False,
    liveness_policy: DesktopLivenessPolicy | None = None,
) -> DesktopRuntimeStatus | None:
    try:
        status = discover_desktop_runtime(
            channel=channel,
            storage_dir=storage_dir,
            route=route,
            cwd=cwd,
            liveness_policy=liveness_policy,
        )
    except DesktopRuntimeDiscoveryError as exc:
        typer.secho(f"error: {exc.message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from exc

    if force_restart and status.state != "absent":
        force_restart_desktop_runtime_or_exit(status, channel=channel)
    elif status.state == "live":
        return status
    elif status.state == "stale":
        recover_desktop_runtime_or_exit(status, channel=channel, announce=False)
    elif status.state in {"not-serving", "wedged"}:
        recover_desktop_runtime_or_exit(status, channel=channel, announce=True)
    elif status.state == "unhealthy":
        refuse_desktop_runtime_or_exit(status, channel=channel)

    return None


def recover_desktop_runtime_or_exit(
    status: DesktopRuntimeStatus,
    *,
    channel: str,
    announce: bool,
) -> None:
    if announce:
        reason = _recovery_reason(status)
        typer.secho(
            "warning: recorded desktop runtime for "
            f"channel {channel} has pid {status.pid}, but {_runtime_url(status)} "
            f"{reason}; restarting it.",
            fg=typer.colors.YELLOW,
            err=True,
        )
    _stop_record_or_exit(status, action="recover")


def force_restart_desktop_runtime_or_exit(
    status: DesktopRuntimeStatus,
    *,
    channel: str,
) -> None:
    typer.secho(
        "warning: force restarting desktop runtime for "
        f"channel {channel}; terminating pid {status.pid} at {_runtime_url(status)}.",
        fg=typer.colors.YELLOW,
        err=True,
    )
    _stop_record_or_exit(status, action="force restart")


def refuse_desktop_runtime_or_exit(
    status: DesktopRuntimeStatus,
    *,
    channel: str,
) -> NoReturn:
    typer.secho(
        "error: refusing to restart desktop runtime automatically.",
        fg=typer.colors.RED,
        err=True,
    )
    typer.echo(
        f"channel {channel} has pid {status.pid} at {_runtime_url(status)} "
        f"after liveness retries ({status.reason or status.state}). "
        "It may be busy or wedged. To terminate it explicitly, run "
        "`transport-matters desktop --force-restart`. For diagnostics, run "
        "`transport-matters doctor`.",
        err=True,
    )
    raise typer.Exit(1)


def _stop_record_or_exit(status: DesktopRuntimeStatus, *, action: str) -> None:
    try:
        stop_desktop_record(Path(status.record_path))
    except OSError as exc:
        hint = f" Inspect logs at {status.log_path}." if status.log_path else ""
        typer.secho(
            f"error: could not {action} desktop runtime at {status.record_path}: {exc}."
            f"{hint} Remove the runtime record or stop the process, then retry.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(1) from exc


def _runtime_url(status: DesktopRuntimeStatus) -> str:
    return status.health_url or status.api_base_url or status.record_path


def _recovery_reason(status: DesktopRuntimeStatus) -> str:
    if status.state == "not-serving":
        return "refused connections after liveness retries"
    if status.state == "wedged":
        return "did not answer after liveness retries"
    return f"failed liveness checks ({status.reason or status.state})"
