"""Seed managed client homes from the user's default CLI homes.

Claude Code authentication still depends on the platform credential store on
macOS. This seeder copies only account metadata plus trust state, so other
platform credential layouts may still require a manual login.
"""

import contextlib
import json
import os
import re
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from transport_matters import env_keys
from transport_matters.launch_environment import (
    CLIENT_NAME_CLAUDE,
    CLIENT_NAME_CODEX,
    HOME_DIR_ENV_BY_CLIENT,
    LOOPBACK_NO_PROXY,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

_CLAUDE_CONFIG_ENV = "CLAUDE_CONFIG_DIR"
_CODEX_HOME_ENV = "CODEX_HOME"
_CLAUDE_CONFIG_FILENAME = ".claude.json"
_CLAUDE_SETTINGS_FILENAME = "settings.json"
_CLAUDE_CREDENTIAL_FILENAME = ".credentials.json"
_CLAUDE_SKIP_DANGEROUS_KEY = "skipDangerousModePermissionPrompt"
_CODEX_AUTH_FILENAME = "auth.json"
_CODEX_CONFIG_FILENAME = "config.toml"
_CODEX_HOOK_TRUST_SOURCE_ENV = "TRANSPORT_MATTERS_CODEX_HOOK_TRUST_SOURCE_HOME"
_TRUSTED = "trusted"
_TRUST_LEVEL_LINE = 'trust_level = "trusted"'
_TRUST_LEVEL_RE = re.compile(r"^\s*trust_level\s*=")
_TOML_TABLE_RE = re.compile(r"^\s*\[")
# Codex keys ``[hooks.state."<abs hooks-file path>:<event>:<i>:<j>"]`` trust by the absolute
# path of the hooks file under ``CODEX_HOME``. The capture matches the quoted TOML basic-string
# key (escaped ``"``/``\`` honoured) so the overlay can repoint its source-home prefix.
_CODEX_HOOKS_STATE_HEADER_RE = re.compile(r'(?m)^\[hooks\.state\."(?P<key>(?:[^"\\]|\\.)*)"\]')
_JSON_FILE_MODE = 0o600
_DIRECTORY_MODE = 0o700
_CLAUDE_ROUTE_ENV_KEY = "ANTHROPIC_BASE_URL"
_NO_PROXY_ENV_KEY = "NO_PROXY"
# Claude daemon control + dispatch state that must stay LOCAL to the overlay (never
# symlinked back to the source). The original route-loss bug is the daemon rebuilding a
# background worker's env from its dispatch state, so ``jobs/`` (queued daemon jobs) is
# route-sensitive exactly like ``daemon*`` and must not resolve to the source home.
_CLAUDE_DAEMON_LOCAL_NAMES = frozenset(
    {
        "daemon",
        "daemon.lock",
        "daemon.log",
        "daemon.status.json",
        "jobs",
    }
)
# Overlay-owned real files, also never symlinked from the content source.
_CLAUDE_OVERLAY_COPIED_NAMES = frozenset(
    {
        _CLAUDE_CONFIG_FILENAME,
        _CLAUDE_SETTINGS_FILENAME,
    }
)
_CLAUDE_OVERLAY_CREDENTIAL_NAMES = frozenset({_CLAUDE_CREDENTIAL_FILENAME})
_CLAUDE_OVERLAY_LOCAL_NAMES = (
    _CLAUDE_OVERLAY_COPIED_NAMES | _CLAUDE_DAEMON_LOCAL_NAMES | _CLAUDE_OVERLAY_CREDENTIAL_NAMES
)
_CODEX_OVERLAY_COPIED_NAMES = frozenset({_CODEX_CONFIG_FILENAME})
_CODEX_OVERLAY_CREDENTIAL_NAMES = frozenset({_CODEX_AUTH_FILENAME})
_CODEX_OVERLAY_LOCAL_NAMES = _CODEX_OVERLAY_COPIED_NAMES | _CODEX_OVERLAY_CREDENTIAL_NAMES
_OVERLAY_CREDENTIAL_NAMES_BY_CLIENT = {
    CLIENT_NAME_CLAUDE: _CLAUDE_OVERLAY_CREDENTIAL_NAMES,
    CLIENT_NAME_CODEX: _CODEX_OVERLAY_CREDENTIAL_NAMES,
}
# Entries never symlinked into any overlay, regardless of client. A source home that is
# (or contains) a git repo must not leak its ``.git`` into the per-run overlay, where git
# would treat the overlay as a working tree of the source repo.
_OVERLAY_NEVER_SYMLINK_NAMES = frozenset({".git"})


@dataclass(frozen=True, slots=True)
class RuntimeHomeOverlay:
    source_home_dir: Path
    runtime_home_dir: Path


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


class ClaudeSeeder:
    """Seed Claude Code onboarding, account metadata, and cwd trust."""

    client_name = CLIENT_NAME_CLAUDE

    def seed(
        self,
        *,
        home_dir: Path,
        working_dir: Path,
        env: Mapping[str, str],
    ) -> None:
        source = _default_claude_config_path(env)
        target = home_dir / _CLAUDE_CONFIG_FILENAME
        source_config = _read_json_object_if_exists(source)
        config = _read_json_object_if_exists(target)

        if "userID" not in config and "userID" in source_config:
            config["userID"] = source_config["userID"]
        if "oauthAccount" not in config and "oauthAccount" in source_config:
            config["oauthAccount"] = source_config["oauthAccount"]

        config["hasCompletedOnboarding"] = True
        _ensure_claude_trust(config, str(working_dir))
        _write_atomic_json(target, config)
        _ensure_claude_skip_dangerous_prompt(home_dir)


class CodexSeeder:
    """Seed Codex auth and cwd trust."""

    client_name = CLIENT_NAME_CODEX

    def seed(
        self,
        *,
        home_dir: Path,
        working_dir: Path,
        env: Mapping[str, str],
    ) -> None:
        source_home = _default_codex_home(env)
        hook_trust_source = _codex_hook_trust_source_home(env, source_home)
        _copy_secret_file_if_missing(
            source_home / _CODEX_AUTH_FILENAME,
            home_dir / _CODEX_AUTH_FILENAME,
        )
        _relocate_codex_hook_trust_state(
            config_path=home_dir / _CODEX_CONFIG_FILENAME,
            source_home=hook_trust_source,
            overlay_home=home_dir,
        )
        _merge_codex_project_trust(
            home_dir / _CODEX_CONFIG_FILENAME,
            cwd=str(working_dir),
        )


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
        return _default_claude_home(source_env)
    if client_name == CLIENT_NAME_CODEX:
        return _default_codex_home(source_env)
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
    """Build a per-run home overlay while keeping user visible state on source."""
    runtime_home_dir.mkdir(mode=_DIRECTORY_MODE, parents=True, exist_ok=True)
    runtime_home_dir.chmod(_DIRECTORY_MODE)
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

    seed_env = dict(os.environ if env is None else env)
    if explicit_auth_source:
        seed_env[HOME_DIR_ENV_BY_CLIENT[client_name]] = str(auth_source_home_dir)
        if client_name == CLIENT_NAME_CODEX:
            seed_env[_CODEX_HOOK_TRUST_SOURCE_ENV] = str(source_home_dir)
    else:
        seed_env[HOME_DIR_ENV_BY_CLIENT[client_name]] = str(source_home_dir)
    seed_home_dir(
        client_name,
        home_dir=runtime_home_dir,
        working_dir=working_dir,
        env=seed_env,
    )
    _assert_overlay_daemon_is_local(
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
    )
    return RuntimeHomeOverlay(
        source_home_dir=source_home_dir,
        runtime_home_dir=runtime_home_dir,
    )


def apply_claude_proxy_env_settings(
    *,
    runtime_home_dir: Path,
    proxy_url: str,
    run_id: str,
) -> None:
    """Write the run proxy route into the overlay's Claude ``settings.json`` ``env``.

    Merge-only: preserves unrelated settings and unrelated ``env`` keys, replacing
    only the Transport Matters managed keys. ``TRANSPORT_MATTERS_AGENT_HOME_DIR`` is
    the overlay home itself, matching the child's ``CLAUDE_CONFIG_DIR``. Raises
    ``ValueError`` if ``settings.json`` or its ``env`` block is not a JSON object, so a
    malformed overlay fails launch instead of silently dropping the route. Writes
    atomically with restrictive mode and never touches the source home.
    """
    settings_path = runtime_home_dir / _CLAUDE_SETTINGS_FILENAME
    settings = _read_json_object_if_exists(settings_path)
    env = settings.get("env")
    if env is None:
        env = {}
        settings["env"] = env
    if not isinstance(env, dict):
        raise ValueError(f"{settings_path} env must contain a JSON object")
    env[_CLAUDE_ROUTE_ENV_KEY] = proxy_url
    env[env_keys.RUN_ID] = run_id
    env[env_keys.AGENT_HOME_DIR] = str(runtime_home_dir)
    env[_NO_PROXY_ENV_KEY] = LOOPBACK_NO_PROXY
    _write_atomic_json(settings_path, settings)


def _overlay_local_names(client_name: str) -> frozenset[str]:
    if client_name == CLIENT_NAME_CLAUDE:
        return _CLAUDE_OVERLAY_LOCAL_NAMES
    if client_name == CLIENT_NAME_CODEX:
        return _CODEX_OVERLAY_LOCAL_NAMES
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
        if entry.name in local_names or entry.name in _OVERLAY_NEVER_SYMLINK_NAMES:
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
        _copy_secret_file_if_missing(
            source_home_dir / _CLAUDE_SETTINGS_FILENAME,
            runtime_home_dir / _CLAUDE_SETTINGS_FILENAME,
        )
        _copy_secret_file_if_missing(
            _source_claude_config_path(source_home_dir, env),
            runtime_home_dir / _CLAUDE_CONFIG_FILENAME,
        )
        return
    if client_name == CLIENT_NAME_CODEX:
        _copy_secret_file_if_missing(
            source_home_dir / _CODEX_CONFIG_FILENAME,
            runtime_home_dir / _CODEX_CONFIG_FILENAME,
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
        return _OVERLAY_CREDENTIAL_NAMES_BY_CLIENT[client_name]
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
    configured_home = source_env.get(_CLAUDE_CONFIG_ENV)
    if configured_home is not None:
        return Path(configured_home).expanduser() / _CLAUDE_CONFIG_FILENAME
    native_home = Path.home() / ".claude"
    if source_home_dir == native_home:
        return Path.home() / _CLAUDE_CONFIG_FILENAME
    return source_home_dir / _CLAUDE_CONFIG_FILENAME


def _assert_overlay_daemon_is_local(
    *,
    source_home_dir: Path,
    runtime_home_dir: Path,
) -> None:
    """Fail closed if any daemon control/dispatch entry resolves back to the source home.

    Covers every name in :data:`_CLAUDE_DAEMON_LOCAL_NAMES` (``daemon*`` and ``jobs``), so a
    captured run can never share the source daemon's dispatch state and silently drop the
    route through a background worker.
    """
    for name in _CLAUDE_DAEMON_LOCAL_NAMES:
        runtime_entry = runtime_home_dir / name
        if runtime_entry.is_symlink() and runtime_entry.resolve(strict=False) == (
            source_home_dir / name
        ).resolve(strict=False):
            raise ValueError(
                f"runtime overlay {name!r} must not resolve to the source home daemon state"
            )


def _default_claude_config_path(env: Mapping[str, str]) -> Path:
    config_dir = env.get(_CLAUDE_CONFIG_ENV)
    if config_dir:
        return Path(config_dir).expanduser() / _CLAUDE_CONFIG_FILENAME
    return Path.home() / _CLAUDE_CONFIG_FILENAME


def _default_claude_home(env: Mapping[str, str]) -> Path:
    config_dir = env.get(_CLAUDE_CONFIG_ENV)
    if config_dir:
        return Path(config_dir).expanduser()
    return Path.home() / ".claude"


def _default_codex_home(env: Mapping[str, str]) -> Path:
    codex_home = env.get(_CODEX_HOME_ENV)
    if codex_home:
        return Path(codex_home).expanduser()
    return Path.home() / ".codex"


def _codex_hook_trust_source_home(env: Mapping[str, str], fallback: Path) -> Path:
    source = env.get(_CODEX_HOOK_TRUST_SOURCE_ENV)
    if source:
        return Path(source).expanduser()
    return fallback


def claude_projects_root(home_dir: Path | None, env: Mapping[str, str]) -> Path:
    """The directory claude writes session transcripts to: ``<claude config home>/projects``.

    The claude home is the managed ``--agent-home-dir`` when set (it becomes the child's
    ``CLAUDE_CONFIG_DIR`` in ``build_managed_child_env``), else claude's native default
    (``$CLAUDE_CONFIG_DIR`` or ``~/.claude``). The managed-mint launcher (§5.2c) computes its owned
    ``source_descriptor`` under this root so it lands exactly where ``claude --session-id`` writes —
    same resolution as the child, so the descriptor never points off claude's real transcript root."""
    home = home_dir if home_dir is not None else _default_claude_home(env)
    return home / "projects"


def codex_sessions_root(home_dir: Path | None, env: Mapping[str, str]) -> Path:
    """The directory codex writes session rollouts to: ``<codex home>/sessions``.

    The codex home is the managed ``--agent-home-dir`` when set (it becomes the child's ``CODEX_HOME`` in
    ``build_managed_child_env``), else codex's native default (``$CODEX_HOME`` or ``~/.codex``). The
    managed-mint launcher (§5.2b) seeds its owned rollout here so it lands exactly where the resumed
    codex appends — same resolution as the child, so the seed never lands off codex's real root."""
    home = home_dir if home_dir is not None else _default_codex_home(env)
    return home / "sessions"


def _read_json_object_if_exists(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


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
    """Seed settings.json so a managed Claude skips the dangerous-mode prompt.

    Merge-only: preserves any existing settings keys and is idempotent.
    """
    target = home_dir / _CLAUDE_SETTINGS_FILENAME
    settings = _read_json_object_if_exists(target)
    if settings.get(_CLAUDE_SKIP_DANGEROUS_KEY) is True:
        return
    settings[_CLAUDE_SKIP_DANGEROUS_KEY] = True
    _write_atomic_json(target, settings)


def _write_atomic_json(path: Path, value: dict[str, Any]) -> None:
    body = json.dumps(value, indent=2).encode("utf-8") + b"\n"
    _write_atomic_secret(path, body)


def _copy_secret_file_if_missing(source: Path, target: Path) -> None:
    try:
        body = source.read_bytes()
    except FileNotFoundError:
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(
            target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            _JSON_FILE_MODE,
        )
    except FileExistsError:
        return

    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        target.chmod(_JSON_FILE_MODE)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            target.unlink()
        raise


def _write_atomic_secret(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _JSON_FILE_MODE)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(body)
        tmp.replace(path)
        path.chmod(_JSON_FILE_MODE)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise


def _relocate_codex_hook_trust_state(
    *,
    config_path: Path,
    source_home: Path,
    overlay_home: Path,
) -> None:
    """Repoint copied Codex hook trust-state keys at the overlay home.

    Codex keys ``[hooks.state]`` trust by the absolute path of the hooks file it loads from
    ``CODEX_HOME``. The overlay copies ``config.toml`` (carrying source-home keys) yet serves
    ``hooks.json`` from the overlay home, so without this the child recomputes every hook as
    untrusted and shows the startup "hooks need review" prompt. Only the table-header key
    prefixes move; the unchanged, symlinked hook definitions still hash to their stored
    ``trusted_hash`` under the overlay path, so trust carries over silently.
    """
    if source_home == overlay_home:
        return
    try:
        current = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return

    src = _toml_basic_string(str(source_home))[1:-1]
    dst = _toml_basic_string(str(overlay_home))[1:-1]
    if src == dst:
        return
    prefix = f"{src}/"

    def _repoint(match: re.Match[str]) -> str:
        key = match.group("key")
        if not key.startswith(prefix):
            return match.group(0)
        return f'[hooks.state."{dst}/{key[len(prefix) :]}"]'

    updated = _CODEX_HOOKS_STATE_HEADER_RE.sub(_repoint, current)
    if updated == current:
        return
    _parse_codex_config(updated, config_path)
    _write_atomic_secret(config_path, updated.encode("utf-8"))


def _merge_codex_project_trust(config_path: Path, *, cwd: str) -> None:
    try:
        current = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""

    parsed = _parse_codex_config(current, config_path)
    if _project_is_trusted(parsed, cwd):
        return

    updated = _write_project_trust(current, cwd=cwd)
    _parse_codex_config(updated, config_path)
    _write_atomic_secret(config_path, updated.encode("utf-8"))


def _parse_codex_config(body: str, path: Path) -> dict[str, Any]:
    try:
        value = tomllib.loads(body) if body.strip() else {}
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path} contains invalid TOML") from exc
    return value


def _project_is_trusted(config: dict[str, Any], cwd: str) -> bool:
    projects = config.get("projects")
    if not isinstance(projects, dict):
        return False
    project = projects.get(cwd)
    return isinstance(project, dict) and project.get("trust_level") == _TRUSTED


def _write_project_trust(current: str, *, cwd: str) -> str:
    header = _codex_project_header(cwd)
    lines = current.splitlines(keepends=True)
    start = _find_table_header(lines, header)
    if start is None:
        return _append_project_trust(current, header)

    section_end = _find_table_end(lines, start + 1)
    for index in range(start + 1, section_end):
        if _TRUST_LEVEL_RE.match(lines[index]):
            lines[index] = _with_original_newline(lines[index], _TRUST_LEVEL_LINE)
            return "".join(lines)

    _ensure_line_break_before_insert(lines, section_end)
    lines.insert(section_end, f"{_TRUST_LEVEL_LINE}\n")
    return "".join(lines)


def _codex_project_header(cwd: str) -> str:
    return f"[projects.{_toml_basic_string(cwd)}]"


def _toml_basic_string(value: str) -> str:
    replacements = {
        "\\": "\\\\",
        '"': '\\"',
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
    }
    return '"' + "".join(replacements.get(char, char) for char in value) + '"'


def _find_table_header(lines: list[str], header: str) -> int | None:
    for index, line in enumerate(lines):
        if line.strip() == header:
            return index
    return None


def _find_table_end(lines: list[str], start: int) -> int:
    for index in range(start, len(lines)):
        if _TOML_TABLE_RE.match(lines[index]):
            return index
    return len(lines)


def _ensure_line_break_before_insert(lines: list[str], index: int) -> None:
    if index == 0:
        return
    previous = lines[index - 1]
    if not previous.endswith(("\n", "\r")):
        lines[index - 1] = f"{previous}\n"


def _append_project_trust(current: str, header: str) -> str:
    prefix = current
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    spacer = "\n" if prefix else ""
    return f"{prefix}{spacer}{header}\n{_TRUST_LEVEL_LINE}\n"


def _with_original_newline(original: str, replacement: str) -> str:
    if original.endswith("\r\n"):
        return f"{replacement}\r\n"
    if original.endswith("\n"):
        return f"{replacement}\n"
    return replacement
