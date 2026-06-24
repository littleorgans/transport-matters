"""Shared desktop launch configuration resolvers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

import typer

from transport_matters.storage_roots import default_storage_root

if TYPE_CHECKING:
    from collections.abc import Mapping

RouteName = Literal["canvas", "canvas-lab"]


def normalize_desktop_route(route: str) -> RouteName:
    normalized = route.lower()
    if normalized not in {"canvas", "canvas-lab"}:
        msg = f"unsupported desktop route: {route}"
        raise typer.BadParameter(msg)
    return cast("RouteName", normalized)


def resolve_desktop_work_dir(work_dir: Path | None) -> Path:
    resolved = (work_dir if work_dir is not None else Path.cwd()).expanduser().resolve()
    if not resolved.exists():
        msg = f"work directory does not exist: {resolved}"
        raise typer.BadParameter(msg)
    if not resolved.is_dir():
        msg = f"work directory is not a directory: {resolved}"
        raise typer.BadParameter(msg)
    return resolved


def resolve_desktop_storage_dir(
    storage_dir: Path | None,
    *,
    channel: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    return (
        (storage_dir if storage_dir is not None else default_storage_root(channel, env=env))
        .expanduser()
        .resolve()
    )
