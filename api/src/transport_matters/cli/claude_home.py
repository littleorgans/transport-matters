"""Claude managed home seeding and path helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any  # Any: Claude JSON config accepts arbitrary values.

from transport_matters import env_keys
from transport_matters.launch_environment import HARNESS_NAME_CLAUDE, LOOPBACK_NO_PROXY

from . import home_constants, home_io

if TYPE_CHECKING:
    from collections.abc import Mapping


class ClaudeSeeder:
    """Seed Claude Code onboarding, account metadata, and cwd trust."""

    harness: str = HARNESS_NAME_CLAUDE

    def seed(
        self,
        *,
        home_dir: Path,
        working_dir: Path,
        env: Mapping[str, str],
    ) -> None:
        source = _default_claude_config_path(env)
        target = home_dir / home_constants._CLAUDE_CONFIG_FILENAME
        source_config = home_io._read_json_object_if_exists(source)
        config = home_io._read_json_object_if_exists(target)

        if "userID" not in config and "userID" in source_config:
            config["userID"] = source_config["userID"]
        if "oauthAccount" not in config and "oauthAccount" in source_config:
            config["oauthAccount"] = source_config["oauthAccount"]

        config["hasCompletedOnboarding"] = True
        _ensure_claude_trust(config, str(working_dir))
        home_io.write_atomic_json(target, config)
        _ensure_claude_skip_dangerous_prompt(home_dir)


def apply_claude_proxy_env_settings(
    *,
    runtime_home_dir: Path,
    proxy_url: str,
    run_id: str,
) -> None:
    """Write the run proxy route into the overlay's Claude ``settings.json`` ``env``.

    Merge only: preserves unrelated settings and unrelated ``env`` keys, replacing
    only the Transport Matters managed keys. ``TRANSPORT_MATTERS_AGENT_HOME_DIR`` is
    the overlay home itself, matching the child's ``CLAUDE_CONFIG_DIR``. Raises
    ``ValueError`` if ``settings.json`` or its ``env`` block is not a JSON object, so a
    malformed overlay fails launch instead of silently dropping the route. Writes
    atomically with restrictive mode and never touches the source home.
    """
    settings_path = runtime_home_dir / home_constants._CLAUDE_SETTINGS_FILENAME
    settings = home_io._read_json_object_if_exists(settings_path)
    env = settings.get("env")
    if env is None:
        env = {}
        settings["env"] = env
    if not isinstance(env, dict):
        raise ValueError(f"{settings_path} env must contain a JSON object")
    env[home_constants._CLAUDE_ROUTE_ENV_KEY] = proxy_url
    env[env_keys.RUN_ID] = run_id
    env[env_keys.AGENT_HOME_DIR] = str(runtime_home_dir)
    env[home_constants._NO_PROXY_ENV_KEY] = LOOPBACK_NO_PROXY
    home_io.write_atomic_json(settings_path, settings)


def default_claude_home(env: Mapping[str, str]) -> Path:
    config_dir = env.get(home_constants._CLAUDE_CONFIG_ENV)
    if config_dir:
        return Path(config_dir).expanduser()
    return Path.home() / ".claude"


def claude_projects_root(home_dir: Path | None, env: Mapping[str, str]) -> Path:
    """The directory claude writes session transcripts to."""
    home = home_dir if home_dir is not None else default_claude_home(env)
    return home / "projects"


def _default_claude_config_path(env: Mapping[str, str]) -> Path:
    config_dir = env.get(home_constants._CLAUDE_CONFIG_ENV)
    if config_dir:
        return Path(config_dir).expanduser() / home_constants._CLAUDE_CONFIG_FILENAME
    return Path.home() / home_constants._CLAUDE_CONFIG_FILENAME


def _ensure_claude_trust(config: dict[str, Any], cwd: str) -> None:
    projects = config.get("projects")
    if not isinstance(projects, dict):
        projects = {}
        config["projects"] = projects

    project = projects.get(cwd)
    if not isinstance(project, dict):
        project = {}
        projects[cwd] = project
    project["hasTrustDialogAccepted"] = True


def _ensure_claude_skip_dangerous_prompt(home_dir: Path) -> None:
    """Seed settings.json so a managed Claude skips the dangerous mode prompt.

    Merge only: preserves any existing settings keys and is idempotent.
    """
    target = home_dir / home_constants._CLAUDE_SETTINGS_FILENAME
    settings = home_io._read_json_object_if_exists(target)
    if settings.get(home_constants._CLAUDE_SKIP_DANGEROUS_KEY) is True:
        return
    settings[home_constants._CLAUDE_SKIP_DANGEROUS_KEY] = True
    home_io.write_atomic_json(target, settings)
