"""Desktop runtime recovery and refusal policy."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer

from .desktop_runtime import DesktopRuntimeStatus, stop_desktop_record


def recover_desktop_runtime_or_exit(
    status: DesktopRuntimeStatus,
    *,
    channel: str,
    announce: bool,
) -> None:
    if announce:
        typer.secho(
            "warning: recorded desktop runtime for "
            f"channel {channel} has pid {status.pid}, but {_runtime_url(status)} "
            "refused connections after liveness retries; restarting it.",
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
