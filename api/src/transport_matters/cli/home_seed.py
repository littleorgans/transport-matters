"""Seed managed client homes from the user's default CLI homes.

Claude Code authentication still depends on the platform credential store on
macOS. This seeder copies only account metadata plus trust state, so other
platform credential layouts may still require a manual login.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tomllib
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from .launch_runtime import CLIENT_NAME_CLAUDE, CLIENT_NAME_CODEX

if TYPE_CHECKING:
    from collections.abc import Mapping

_CLAUDE_CONFIG_ENV = "CLAUDE_CONFIG_DIR"
_CODEX_HOME_ENV = "CODEX_HOME"
_CLAUDE_CONFIG_FILENAME = ".claude.json"
_CODEX_AUTH_FILENAME = "auth.json"
_CODEX_CONFIG_FILENAME = "config.toml"
_TRUSTED = "trusted"
_TRUST_LEVEL_LINE = 'trust_level = "trusted"'
_TRUST_LEVEL_RE = re.compile(r"^\s*trust_level\s*=")
_TOML_TABLE_RE = re.compile(r"^\s*\[")
_JSON_FILE_MODE = 0o600


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
        _copy_secret_file_if_missing(
            source_home / _CODEX_AUTH_FILENAME,
            home_dir / _CODEX_AUTH_FILENAME,
        )
        _merge_codex_project_trust(
            home_dir / _CODEX_CONFIG_FILENAME,
            cwd=str(working_dir),
        )


_SEEDERS: tuple[HarnessSeeder, ...] = (ClaudeSeeder(), CodexSeeder())
_SEEDERS_BY_CLIENT: dict[str, HarnessSeeder] = {
    seeder.client_name: seeder for seeder in _SEEDERS
}


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
        raise ValueError(
            f"unmapped managed client home seeder: {client_name!r}"
        ) from exc
    seeder.seed(
        home_dir=home_dir,
        working_dir=working_dir,
        env=os.environ if env is None else env,
    )


def _default_claude_config_path(env: Mapping[str, str]) -> Path:
    config_dir = env.get(_CLAUDE_CONFIG_ENV)
    if config_dir:
        return Path(config_dir).expanduser() / _CLAUDE_CONFIG_FILENAME
    return Path.home() / _CLAUDE_CONFIG_FILENAME


def _default_codex_home(env: Mapping[str, str]) -> Path:
    codex_home = env.get(_CODEX_HOME_ENV)
    if codex_home:
        return Path(codex_home).expanduser()
    return Path.home() / ".codex"


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
