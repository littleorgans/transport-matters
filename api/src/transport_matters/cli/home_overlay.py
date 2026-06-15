"""Per-run managed home overlay materialization."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from transport_matters.launch_environment import CLIENT_NAME_CLAUDE, CLIENT_NAME_CODEX

from . import home_constants, home_io

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping


@dataclass(frozen=True, slots=True)
class RuntimeHomeOverlay:
    source_home_dir: Path
    runtime_home_dir: Path


@dataclass(frozen=True, slots=True)
class OverlayMaterialization:
    overlay: RuntimeHomeOverlay
    auth_source_home_dir: Path
    explicit_auth_source: bool


def materialize_runtime_home_overlay(
    client_name: str,
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
    env: Mapping[str, str] | None = None,
    auth_source_home_dir: Path | None = None,
    extra_local_names: Collection[str] = (),
) -> OverlayMaterialization:
    """Build overlay files while keeping user visible state on the source home."""
    runtime_home_dir.mkdir(mode=home_constants._DIRECTORY_MODE, parents=True, exist_ok=True)
    runtime_home_dir.chmod(home_constants._DIRECTORY_MODE)
    source_home_dir = source_home_dir.expanduser()
    explicit_auth_source = auth_source_home_dir is not None
    auth_source_home_dir = (
        auth_source_home_dir.expanduser() if auth_source_home_dir is not None else source_home_dir
    )

    local_names = _overlay_local_names(client_name) | frozenset(extra_local_names)
    _symlink_source_home_entries(
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
        local_names=local_names,
    )
    _copy_overlay_local_files(
        client_name,
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
        env=env,
    )
    _link_overlay_credential_files(
        client_name,
        auth_source_home_dir=auth_source_home_dir,
        runtime_home_dir=runtime_home_dir,
    )

    return OverlayMaterialization(
        overlay=RuntimeHomeOverlay(
            source_home_dir=source_home_dir,
            runtime_home_dir=runtime_home_dir,
        ),
        auth_source_home_dir=auth_source_home_dir,
        explicit_auth_source=explicit_auth_source,
    )


def assert_overlay_daemon_is_local(
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
) -> None:
    """Fail closed if daemon control or dispatch entries resolve back to source."""
    for name in home_constants._CLAUDE_DAEMON_LOCAL_NAMES:
        runtime_entry = runtime_home_dir / name
        if runtime_entry.is_symlink() and runtime_entry.resolve(strict=False) == (
            source_home_dir / name
        ).resolve(strict=False):
            raise ValueError(
                f"runtime overlay {name!r} must not resolve to the source home daemon state"
            )


def _overlay_local_names(client_name: str) -> frozenset[str]:
    if client_name == CLIENT_NAME_CLAUDE:
        return home_constants._CLAUDE_OVERLAY_LOCAL_NAMES
    if client_name == CLIENT_NAME_CODEX:
        return home_constants._CODEX_OVERLAY_LOCAL_NAMES
    raise ValueError(f"unmapped managed client home seeder: {client_name!r}")


def _symlink_source_home_entries(
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
    local_names: frozenset[str],
) -> None:
    try:
        entries = list(source_home_dir.iterdir())
    except FileNotFoundError:
        return
    for entry in entries:
        if entry.name in local_names or entry.name in home_constants._OVERLAY_NEVER_SYMLINK_NAMES:
            continue
        target = runtime_home_dir / entry.name
        if target.exists() or target.is_symlink():
            continue
        target.symlink_to(entry, target_is_directory=entry.is_dir())


def _copy_overlay_local_files(
    client_name: str,
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
    env: Mapping[str, str] | None,
) -> None:
    if client_name == CLIENT_NAME_CLAUDE:
        home_io._copy_secret_file_if_missing(
            source_home_dir / home_constants._CLAUDE_SETTINGS_FILENAME,
            runtime_home_dir / home_constants._CLAUDE_SETTINGS_FILENAME,
        )
        home_io._copy_secret_file_if_missing(
            _source_claude_config_path(source_home_dir, env),
            runtime_home_dir / home_constants._CLAUDE_CONFIG_FILENAME,
        )
        return
    if client_name == CLIENT_NAME_CODEX:
        home_io._copy_secret_file_if_missing(
            source_home_dir / home_constants._CODEX_CONFIG_FILENAME,
            runtime_home_dir / home_constants._CODEX_CONFIG_FILENAME,
        )
        return
    raise ValueError(f"unmapped managed client home seeder: {client_name!r}")


def _link_overlay_credential_files(
    client_name: str,
    *,
    auth_source_home_dir: Path,
    runtime_home_dir: Path,
) -> None:
    for name in _overlay_credential_names(client_name):
        _symlink_file_if_exists(auth_source_home_dir / name, runtime_home_dir / name)


def _overlay_credential_names(client_name: str) -> frozenset[str]:
    try:
        return home_constants._OVERLAY_CREDENTIAL_NAMES_BY_CLIENT[client_name]
    except KeyError as exc:
        raise ValueError(f"unmapped managed client home seeder: {client_name!r}") from exc


def _symlink_file_if_exists(source: Path, target: Path) -> None:
    if not source.is_file():
        return
    if target.exists() or target.is_symlink():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source.resolve())


def _source_claude_config_path(
    source_home_dir: Path,
    env: Mapping[str, str] | None,
) -> Path:
    source_env = os.environ if env is None else env
    configured_home = source_env.get(home_constants._CLAUDE_CONFIG_ENV)
    if configured_home is not None:
        return Path(configured_home).expanduser() / home_constants._CLAUDE_CONFIG_FILENAME
    native_home = Path.home() / ".claude"
    if source_home_dir == native_home:
        return Path.home() / home_constants._CLAUDE_CONFIG_FILENAME
    return source_home_dir / home_constants._CLAUDE_CONFIG_FILENAME
