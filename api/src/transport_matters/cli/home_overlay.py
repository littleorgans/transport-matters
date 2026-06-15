"""Per-run managed home overlay materialization."""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


@dataclass(frozen=True, slots=True)
class _TemplateMaterializationPolicy:
    content_names: frozenset[str]
    copy_names: frozenset[str]
    local_writable_names: frozenset[str]
    credential_names: frozenset[str]
    reject_names: frozenset[str]


_CLAUDE_TEMPLATE_CONTENT_NAMES = frozenset(
    {
        "CLAUDE.md",
        "agents",
        "commands",
        "hooks",
        "output-styles",
        "plugins",
        "skills",
        "statusline-command.sh",
    }
)
_CODEX_TEMPLATE_CONTENT_NAMES = frozenset(
    {
        "AGENTS.md",
        "developer_instructions",
        "hooks",
        "hooks.json",
        "plugins",
        "skills",
        "vendor_imports",
    }
)
_CLAUDE_TEMPLATE_LOCAL_WRITABLE_NAMES = home_constants._CLAUDE_DAEMON_LOCAL_NAMES | frozenset(
    {
        "cache",
        "downloads",
        "file-history",
        "history.jsonl",
        "mcp-needs-auth-cache.json",
        "paste-cache",
        "projects",
        "session-env",
        "sessions",
        "shell-snapshots",
        "stats-cache.json",
    }
)
_CODEX_TEMPLATE_LOCAL_WRITABLE_NAMES = frozenset(
    {
        ".codex-global-state.json",
        ".codex-global-state.json.bak",
        ".tmp",
        "ambient-suggestions",
        "archived_sessions",
        "cache",
        "computer-use",
        "generated_images",
        "goals_1.sqlite",
        "goals_1.sqlite-shm",
        "goals_1.sqlite-wal",
        "history.jsonl",
        "installation_id",
        "internal_storage.json",
        "log",
        "logs_2.sqlite",
        "logs_2.sqlite-shm",
        "logs_2.sqlite-wal",
        "memories_1.sqlite",
        "memories_1.sqlite-shm",
        "memories_1.sqlite-wal",
        "models_cache.json",
        "node_repl",
        "process_manager",
        "session_index.jsonl",
        "sessions",
        "shell_snapshots",
        "sqlite",
        "state_5.sqlite",
        "state_5.sqlite-shm",
        "state_5.sqlite-wal",
        "tmp",
        "version.json",
    }
)
_CODEX_CONFIG_SECRET_KEYS = frozenset(
    {
        "access_token",
        "account",
        "api_key",
        "auth",
        "authentication",
        "authorization",
        "credential",
        "credentials",
        "id_token",
        "oauth",
        "refresh_token",
        "token",
        "tokens",
    }
)
_CODEX_CONFIG_EXACT_ONLY_SECRET_KEYS = frozenset({"account"})
_CODEX_CONFIG_DELIMITED_SECRET_KEYS = (
    _CODEX_CONFIG_SECRET_KEYS - _CODEX_CONFIG_EXACT_ONLY_SECRET_KEYS
)
_CODEX_CONFIG_KEY_DELIMITER_PATTERN = re.compile(r"[_\-.]+")


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
    source_home_dir, auth_source_home_dir, explicit_auth_source = _prepare_materialization_dirs(
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
        auth_source_home_dir=auth_source_home_dir,
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

    return _overlay_materialization(
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
        auth_source_home_dir=auth_source_home_dir,
        explicit_auth_source=explicit_auth_source,
    )


def materialize_runtime_home_template_overlay(
    client_name: str,
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
    env: Mapping[str, str] | None = None,
    auth_source_home_dir: Path | None = None,
) -> OverlayMaterialization:
    """Build a template overlay with safe local state and symlinked content."""
    source_home_dir = source_home_dir.expanduser()
    validate_runtime_home_template(client_name, source_home_dir)
    source_home_dir, auth_source_home_dir, explicit_auth_source = _prepare_materialization_dirs(
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
        auth_source_home_dir=auth_source_home_dir,
    )

    policy = _template_materialization_policy(client_name)
    _symlink_template_content_entries(
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
        policy=policy,
    )
    _materialize_local_writable_entries(
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
        local_writable_names=policy.local_writable_names,
    )
    _copy_overlay_local_files(
        client_name,
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
        env=env,
        pin_claude_config_to_source=True,
    )
    _link_overlay_credential_files(
        client_name,
        auth_source_home_dir=auth_source_home_dir,
        runtime_home_dir=runtime_home_dir,
    )

    return _overlay_materialization(
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
        auth_source_home_dir=auth_source_home_dir,
        explicit_auth_source=explicit_auth_source,
    )


def validate_runtime_home_template(client_name: str, template_home: Path) -> None:
    """Reject templates that contain secrets."""
    template_home = template_home.expanduser()
    policy = _template_materialization_policy(client_name)
    if not template_home.exists():
        raise ValueError(f"runtime template {template_home} does not exist")
    if not template_home.is_dir():
        raise ValueError(f"runtime template {template_home} is not a directory")
    entries = list(template_home.iterdir())

    for entry in entries:
        if entry.name in policy.credential_names:
            raise ValueError(
                f"runtime template {template_home} contains credential file {entry.name!r}"
            )
    _validate_template_secret_free(client_name, template_home)


def _prepare_materialization_dirs(
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
    auth_source_home_dir: Path | None,
) -> tuple[Path, Path, bool]:
    runtime_home_dir.mkdir(mode=home_constants._DIRECTORY_MODE, parents=True, exist_ok=True)
    runtime_home_dir.chmod(home_constants._DIRECTORY_MODE)
    source_home_dir = source_home_dir.expanduser()
    explicit_auth_source = auth_source_home_dir is not None
    auth_source_home_dir = (
        auth_source_home_dir.expanduser() if auth_source_home_dir is not None else source_home_dir
    )
    return source_home_dir, auth_source_home_dir, explicit_auth_source


def _overlay_materialization(
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
    auth_source_home_dir: Path,
    explicit_auth_source: bool,
) -> OverlayMaterialization:
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


def _symlink_template_content_entries(
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
    policy: _TemplateMaterializationPolicy,
) -> None:
    try:
        entries = list(source_home_dir.iterdir())
    except FileNotFoundError:
        return
    local_names = (
        policy.copy_names
        | policy.local_writable_names
        | policy.credential_names
        | policy.reject_names
    )
    for entry in entries:
        if entry.name in local_names:
            continue
        target = runtime_home_dir / entry.name
        if target.exists() or target.is_symlink():
            continue
        target.symlink_to(entry, target_is_directory=entry.is_dir())


def _materialize_local_writable_entries(
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
    local_writable_names: frozenset[str],
) -> None:
    for name in local_writable_names:
        source_entry = source_home_dir / name
        if source_entry.is_dir():
            (runtime_home_dir / name).mkdir(
                mode=home_constants._DIRECTORY_MODE,
                parents=True,
                exist_ok=True,
            )


def _copy_overlay_local_files(
    client_name: str,
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
    env: Mapping[str, str] | None,
    pin_claude_config_to_source: bool = False,
) -> None:
    if client_name == CLIENT_NAME_CLAUDE:
        claude_config_source = (
            source_home_dir / home_constants._CLAUDE_CONFIG_FILENAME
            if pin_claude_config_to_source
            else _source_claude_config_path(source_home_dir, env)
        )
        home_io._copy_secret_file_if_missing(
            source_home_dir / home_constants._CLAUDE_SETTINGS_FILENAME,
            runtime_home_dir / home_constants._CLAUDE_SETTINGS_FILENAME,
        )
        home_io._copy_secret_file_if_missing(
            claude_config_source,
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


def _template_materialization_policy(client_name: str) -> _TemplateMaterializationPolicy:
    if client_name == CLIENT_NAME_CLAUDE:
        return _TemplateMaterializationPolicy(
            content_names=_CLAUDE_TEMPLATE_CONTENT_NAMES,
            copy_names=home_constants._CLAUDE_OVERLAY_COPIED_NAMES,
            local_writable_names=_CLAUDE_TEMPLATE_LOCAL_WRITABLE_NAMES,
            credential_names=home_constants._CLAUDE_OVERLAY_CREDENTIAL_NAMES,
            reject_names=home_constants._OVERLAY_NEVER_SYMLINK_NAMES,
        )
    if client_name == CLIENT_NAME_CODEX:
        return _TemplateMaterializationPolicy(
            content_names=_CODEX_TEMPLATE_CONTENT_NAMES,
            copy_names=home_constants._CODEX_OVERLAY_COPIED_NAMES,
            local_writable_names=_CODEX_TEMPLATE_LOCAL_WRITABLE_NAMES,
            credential_names=home_constants._CODEX_OVERLAY_CREDENTIAL_NAMES,
            reject_names=home_constants._OVERLAY_NEVER_SYMLINK_NAMES,
        )
    raise ValueError(f"unmapped managed client home seeder: {client_name!r}")


def _validate_template_secret_free(client_name: str, template_home: Path) -> None:
    if client_name == CLIENT_NAME_CLAUDE:
        config = home_io._read_json_object_if_exists(
            template_home / home_constants._CLAUDE_CONFIG_FILENAME
        )
        for field_name in ("oauthAccount", "userID"):
            if field_name in config:
                raise ValueError(
                    f"runtime template {template_home} contains Claude account field {field_name!r}"
                )
        return
    if client_name == CLIENT_NAME_CODEX:
        config_path = template_home / home_constants._CODEX_CONFIG_FILENAME
        try:
            config = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"{config_path} must contain valid TOML") from exc
        secret_path = _codex_config_secret_path(config)
        if secret_path is not None:
            raise ValueError(
                f"runtime template {template_home} contains Codex auth material at {secret_path}"
            )
        return
    raise ValueError(f"unmapped managed client home seeder: {client_name!r}")


def _codex_config_secret_path(value: Any, *, prefix: str = "") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_path = f"{prefix}.{key}" if prefix else str(key)
            if _codex_config_key_has_secret_indicator(key):
                return key_path
            found = _codex_config_secret_path(child, prefix=key_path)
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _codex_config_secret_path(child, prefix=f"{prefix}[{index}]")
            if found is not None:
                return found
    return None


def _codex_config_key_has_secret_indicator(key: object) -> bool:
    normalized = str(key).lower()
    if normalized in _CODEX_CONFIG_SECRET_KEYS:
        return True
    key_parts = tuple(
        part for part in _CODEX_CONFIG_KEY_DELIMITER_PATTERN.split(normalized) if part
    )
    return any(
        _codex_config_key_matches_indicator(normalized, key_parts, indicator)
        for indicator in _CODEX_CONFIG_DELIMITED_SECRET_KEYS
    )


def _codex_config_key_matches_indicator(
    key: str,
    key_parts: tuple[str, ...],
    indicator: str,
) -> bool:
    if key.endswith(indicator):
        return True
    indicator_parts = tuple(
        part for part in _CODEX_CONFIG_KEY_DELIMITER_PATTERN.split(indicator) if part
    )
    if len(indicator_parts) == 1:
        return indicator_parts[0] in key_parts
    return any(
        key_parts[index : index + len(indicator_parts)] == indicator_parts
        for index in range(len(key_parts) - len(indicator_parts) + 1)
    )


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
