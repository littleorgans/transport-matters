"""Managed home seeder orchestration."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Protocol

from transport_matters.launch_environment import (
    HARNESS_NAME_CLAUDE,
    HARNESS_NAME_CODEX,
    HOME_DIR_ENV_BY_HARNESS,
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

    harness: str

    def seed(
        self,
        *,
        home_dir: Path,
        working_dir: Path,
        env: Mapping[str, str],
    ) -> None:
        """Seed *home_dir* for *working_dir* from the default client home."""


_SEEDERS: tuple[HarnessSeeder, ...] = (ClaudeSeeder(), CodexSeeder())
_SEEDERS_BY_HARNESS: dict[str, HarnessSeeder] = {seeder.harness: seeder for seeder in _SEEDERS}


def seed_home_dir(
    harness: str,
    *,
    home_dir: Path,
    working_dir: Path,
    env: Mapping[str, str] | None = None,
) -> None:
    """Seed *home_dir* for *harness* with auth and cwd trust."""
    try:
        seeder = _SEEDERS_BY_HARNESS[harness]
    except KeyError as exc:
        raise ValueError(f"unmapped managed harness home seeder: {harness!r}") from exc
    seeder.seed(
        home_dir=home_dir,
        working_dir=working_dir,
        env=os.environ if env is None else env,
    )


def resolve_source_home_dir(
    harness: str,
    *,
    home_dir: Path | None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Resolve the operator supplied or native source home for a captured harness."""
    if home_dir is not None:
        return home_dir.expanduser()
    source_env = os.environ if env is None else env
    if harness == HARNESS_NAME_CLAUDE:
        return claude_home.default_claude_home(source_env)
    if harness == HARNESS_NAME_CODEX:
        return codex_home.default_codex_home(source_env)
    raise ValueError(f"unmapped managed harness home seeder: {harness!r}")


def prepare_runtime_home_overlay(
    harness: str,
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
        harness,
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
        env=env,
        auth_source_home_dir=auth_source_home_dir,
        extra_local_names=extra_local_names,
    )
    return _seed_runtime_home_overlay(harness, materialization, working_dir=working_dir, env=env)


def prepare_runtime_home_template_overlay(
    harness: str,
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
    working_dir: Path,
    env: Mapping[str, str] | None = None,
    auth_source_home_dir: Path | None = None,
) -> RuntimeHomeOverlay:
    """Build a template mode overlay from explicit materialization policy."""
    materialization = home_overlay.materialize_runtime_home_template_overlay(
        harness,
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
        env=env,
        auth_source_home_dir=auth_source_home_dir,
    )
    return _seed_runtime_home_overlay(harness, materialization, working_dir=working_dir, env=env)


def validate_runtime_home_template(harness: str, template_home: Path) -> None:
    home_overlay.validate_runtime_home_template(harness, template_home)


def _seed_runtime_home_overlay(
    harness: str,
    materialization: home_overlay.OverlayMaterialization,
    *,
    working_dir: Path,
    env: Mapping[str, str] | None,
) -> RuntimeHomeOverlay:
    seed_env = dict(os.environ if env is None else env)
    if materialization.explicit_auth_source:
        seed_env[HOME_DIR_ENV_BY_HARNESS[harness]] = str(materialization.auth_source_home_dir)
        if harness == HARNESS_NAME_CODEX:
            seed_env[home_constants._CODEX_HOOK_TRUST_SOURCE_ENV] = str(
                materialization.overlay.source_home_dir
            )
    else:
        seed_env[HOME_DIR_ENV_BY_HARNESS[harness]] = str(materialization.overlay.source_home_dir)
    seed_home_dir(
        harness,
        home_dir=materialization.overlay.runtime_home_dir,
        working_dir=working_dir,
        env=seed_env,
    )
    home_overlay.assert_overlay_daemon_is_local(
        source_home_dir=materialization.overlay.source_home_dir,
        runtime_home_dir=materialization.overlay.runtime_home_dir,
    )
    return materialization.overlay
