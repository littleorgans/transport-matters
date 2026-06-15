"""Managed home seeder orchestration."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol

from transport_matters.launch_environment import (
    CLIENT_NAME_CLAUDE,
    CLIENT_NAME_CODEX,
    HOME_DIR_ENV_BY_CLIENT,
)

from . import claude_home, codex_home, home_constants, home_overlay
from .claude_home import ClaudeSeeder
from .codex_home import CodexSeeder

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from pathlib import Path

    from .home_overlay import RuntimeHomeOverlay


class HarnessSeeder(Protocol):
    """Seed one managed client home."""

    client_name: str

    def seed(
        self,
        *,
        home_dir: Path,
        working_dir: Path,
        env: Mapping[str, str],
    ) -> None:
        """Seed *home_dir* for *working_dir* from the default client home."""


_SEEDERS: tuple[HarnessSeeder, ...] = (ClaudeSeeder(), CodexSeeder())
_SEEDERS_BY_CLIENT: dict[str, HarnessSeeder] = {seeder.client_name: seeder for seeder in _SEEDERS}


def seed_home_dir(
    client_name: str,
    *,
    home_dir: Path,
    working_dir: Path,
    env: Mapping[str, str] | None = None,
) -> None:
    """Seed *home_dir* for *client_name* with auth and cwd trust."""
    try:
        seeder = _SEEDERS_BY_CLIENT[client_name]
    except KeyError as exc:
        raise ValueError(f"unmapped managed client home seeder: {client_name!r}") from exc
    seeder.seed(
        home_dir=home_dir,
        working_dir=working_dir,
        env=os.environ if env is None else env,
    )


def resolve_source_home_dir(
    client_name: str,
    *,
    home_dir: Path | None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the operator supplied or native source home for a captured client."""
    if home_dir is not None:
        return home_dir.expanduser()
    source_env = os.environ if env is None else env
    if client_name == CLIENT_NAME_CLAUDE:
        return claude_home.default_claude_home(source_env)
    if client_name == CLIENT_NAME_CODEX:
        return codex_home.default_codex_home(source_env)
    raise ValueError(f"unmapped managed client home seeder: {client_name!r}")


def prepare_runtime_home_overlay(
    client_name: str,
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
    working_dir: Path,
    env: Mapping[str, str] | None = None,
    auth_source_home_dir: Path | None = None,
    extra_local_names: Collection[str] = (),
) -> RuntimeHomeOverlay:
    """Build a per-run home overlay and seed auth plus cwd trust into it."""
    materialization = home_overlay.materialize_runtime_home_overlay(
        client_name,
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
        env=env,
        auth_source_home_dir=auth_source_home_dir,
        extra_local_names=extra_local_names,
    )
    seed_env = dict(os.environ if env is None else env)
    if materialization.explicit_auth_source:
        seed_env[HOME_DIR_ENV_BY_CLIENT[client_name]] = str(materialization.auth_source_home_dir)
        if client_name == CLIENT_NAME_CODEX:
            seed_env[home_constants._CODEX_HOOK_TRUST_SOURCE_ENV] = str(
                materialization.overlay.source_home_dir
            )
    else:
        seed_env[HOME_DIR_ENV_BY_CLIENT[client_name]] = str(materialization.overlay.source_home_dir)
    seed_home_dir(
        client_name,
        home_dir=materialization.overlay.runtime_home_dir,
        working_dir=working_dir,
        env=seed_env,
    )
    home_overlay.assert_overlay_daemon_is_local(
        source_home_dir=materialization.overlay.source_home_dir,
        runtime_home_dir=materialization.overlay.runtime_home_dir,
    )
    return materialization.overlay
