"""Tail detached desktop backend logs."""

from __future__ import annotations

import os
import sys
import time
from collections import deque
from typing import TYPE_CHECKING

import typer

from transport_matters import env_keys
from transport_matters.channel import ChannelSpec, resolve_channel_spec
from transport_matters.storage_roots import default_storage_root

from .desktop_runtime import desktop_log_path
from .identity import CLI_COMMAND

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def run_tail(
    *,
    channel: str | None,
    lines: int,
    follow: bool,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    spec = _resolve_channel_or_exit(channel)
    log_file = desktop_log_path(default_storage_root(spec.id).expanduser().resolve())
    if not log_file.is_file():
        typer.echo(f"error: desktop log not found: {log_file}", err=True)
        raise typer.Exit(1)

    _write_lines(_read_last_lines(log_file, lines))
    if not follow:
        return

    position = log_file.stat().st_size
    try:
        while True:
            position = _print_appended(log_file, position)
            sleep(0.25)
    except KeyboardInterrupt:
        return


def _resolve_channel_or_exit(channel: str | None) -> ChannelSpec:
    try:
        return resolve_channel_spec(channel)
    except (KeyError, ValueError) as exc:
        requested = channel if channel is not None else os.environ.get(env_keys.CHANNEL, "stable")
        typer.secho(
            f"error: unknown channel {requested!r}.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(f"Run `{CLI_COMMAND} channel list` to see available channels.", err=True)
        raise typer.Exit(2) from exc


def _read_last_lines(log_file: Path, limit: int) -> list[str]:
    if limit <= 0:
        return []
    with log_file.open("r", encoding="utf-8", errors="replace") as handle:
        return list(deque(handle, maxlen=limit))


def _print_appended(log_file: Path, position: int) -> int:
    size = log_file.stat().st_size
    if size < position:
        position = 0
    with log_file.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(position)
        chunk = handle.read()
        position = handle.tell()
    if chunk:
        sys.stdout.write(chunk)
        sys.stdout.flush()
    return position


def _write_lines(lines: list[str]) -> None:
    for line in lines:
        sys.stdout.write(line)
    sys.stdout.flush()
