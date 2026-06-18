"""Codex managed home seeding and TOML trust helpers."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any  # Any: parsed TOML values are heterogeneous.

from transport_matters.launch_environment import HARNESS_NAME_CODEX

from . import home_constants, home_io

if TYPE_CHECKING:
    import re
    from collections.abc import Mapping


class CodexSeeder:
    """Seed Codex auth and cwd trust."""

    harness: str = HARNESS_NAME_CODEX

    def seed(
        self,
        *,
        home_dir: Path,
        working_dir: Path,
        env: Mapping[str, str],
    ) -> None:
        source_home = default_codex_home(env)
        hook_trust_source = _codex_hook_trust_source_home(env, source_home)
        home_io._copy_secret_file_if_missing(
            source_home / home_constants._CODEX_AUTH_FILENAME,
            home_dir / home_constants._CODEX_AUTH_FILENAME,
        )
        _relocate_codex_hook_trust_state(
            config_path=home_dir / home_constants._CODEX_CONFIG_FILENAME,
            source_home=hook_trust_source,
            overlay_home=home_dir,
        )
        _merge_codex_project_trust(
            home_dir / home_constants._CODEX_CONFIG_FILENAME,
            cwd=str(working_dir),
        )


def default_codex_home(env: Mapping[str, str]) -> Path:
    codex_home = env.get(home_constants._CODEX_HOME_ENV)
    if codex_home:
        return Path(codex_home).expanduser()
    return Path.home() / ".codex"


def codex_sessions_root(home_dir: Path | None, env: Mapping[str, str]) -> Path:
    """The directory codex writes session rollouts to."""
    home = home_dir if home_dir is not None else default_codex_home(env)
    return home / "sessions"


def _codex_hook_trust_source_home(env: Mapping[str, str], fallback: Path) -> Path:
    source = env.get(home_constants._CODEX_HOOK_TRUST_SOURCE_ENV)
    if source:
        return Path(source).expanduser()
    return fallback


def _relocate_codex_hook_trust_state(
    *,
    config_path: Path,
    source_home: Path,
    overlay_home: Path,
) -> None:
    """Repoint copied Codex hook trust state keys at the overlay home."""
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

    updated = home_constants._CODEX_HOOKS_STATE_HEADER_RE.sub(_repoint, current)
    if updated == current:
        return
    _parse_codex_config(updated, config_path)
    home_io._write_atomic_secret(config_path, updated.encode("utf-8"))


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
    home_io._write_atomic_secret(config_path, updated.encode("utf-8"))


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
    return isinstance(project, dict) and project.get("trust_level") == home_constants._TRUSTED


def _write_project_trust(current: str, *, cwd: str) -> str:
    header = _codex_project_header(cwd)
    lines = current.splitlines(keepends=True)
    start = _find_table_header(lines, header)
    if start is None:
        return _append_project_trust(current, header)

    section_end = _find_table_end(lines, start + 1)
    for index in range(start + 1, section_end):
        if home_constants._TRUST_LEVEL_RE.match(lines[index]):
            lines[index] = _with_original_newline(lines[index], home_constants._TRUST_LEVEL_LINE)
            return "".join(lines)

    _ensure_line_break_before_insert(lines, section_end)
    lines.insert(section_end, f"{home_constants._TRUST_LEVEL_LINE}\n")
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
        if home_constants._TOML_TABLE_RE.match(lines[index]):
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
    return f"{prefix}{spacer}{header}\n{home_constants._TRUST_LEVEL_LINE}\n"


def _with_original_newline(original: str, replacement: str) -> str:
    if original.endswith("\r\n"):
        return f"{replacement}\r\n"
    if original.endswith("\n"):
        return f"{replacement}\n"
    return replacement
