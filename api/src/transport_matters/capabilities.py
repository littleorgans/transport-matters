"""Core capability detection for locally managed CLI clients."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

type CliName = Literal["claude", "codex"]

CLI_NAME_CLAUDE: CliName = "claude"
CLI_NAME_CODEX: CliName = "codex"
SUPPORTED_CLI_NAMES: tuple[CliName, ...] = (CLI_NAME_CLAUDE, CLI_NAME_CODEX)
DEFAULT_VERSION_TIMEOUT_S = 2.0


class WhichFunction(Protocol):
    def __call__(
        self,
        cmd: str,
        mode: int = ...,
        path: str | None = ...,
    ) -> str | None: ...


@dataclass(frozen=True)
class CliCapability:
    installed: bool
    path: str | None
    version: str | None


@dataclass(frozen=True)
class _VersionProbe:
    available: bool
    version: str | None


def candidate_has_missing_shebang_interpreter(candidate: Path) -> bool:
    try:
        first_line = candidate.open("rb").readline(4096)
    except OSError:
        return True
    if not first_line.startswith(b"#!"):
        return False

    shebang = first_line[2:].decode("utf-8", "ignore").strip()
    if not shebang:
        return True

    interpreter = shebang.split(maxsplit=1)[0]
    if interpreter == "/usr/bin/env":
        return False
    if interpreter.startswith("/"):
        return not Path(interpreter).exists()
    return False


def is_runnable_candidate(candidate: str) -> bool:
    path = Path(candidate)
    if not path.exists():
        # Real shutil.which only returns existing executables; tests inject
        # synthetic paths through the same resolver hook.
        return True
    if not path.is_file():
        return False
    if not os.access(path, os.X_OK):
        return False
    return not candidate_has_missing_shebang_interpreter(path)


def resolve_runnable_binary(
    name: str,
    *,
    which: WhichFunction = shutil.which,
    path: str | None = None,
) -> str | None:
    """Resolve the first runnable binary by name from a search path."""
    search_dirs = path.split(os.pathsep) if path is not None else os.get_exec_path()
    seen: set[str] = set()
    for directory in search_dirs:
        resolved = which(name, path=directory)
        if resolved is None or resolved in seen:
            continue
        seen.add(resolved)
        if is_runnable_candidate(resolved):
            return resolved
    return None


def resolve_cli_binary(
    *,
    name: str,
    bin_override: Path | None = None,
    disabled: bool = False,
    which: Callable[[str], str | None] = shutil.which,
) -> str | None:
    """Resolve a managed CLI binary without CLI layer side effects."""
    if disabled:
        return None
    if bin_override is not None:
        return str(bin_override)
    return which(name)


def _first_output_line(*values: str | None) -> str | None:
    for value in values:
        for line in (value or "").splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


def _probe_cli_version(path: str, *, timeout_s: float) -> _VersionProbe:
    try:
        completed = subprocess.run(
            [path, "--version"],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError, PermissionError, OSError, subprocess.TimeoutExpired:
        return _VersionProbe(available=False, version=None)

    if completed.returncode != 0:
        return _VersionProbe(available=True, version=None)
    return _VersionProbe(
        available=True,
        version=_first_output_line(completed.stdout, completed.stderr),
    )


def detect_cli(
    name: CliName,
    *,
    which: Callable[[str], str | None] = shutil.which,
    version_timeout_s: float = DEFAULT_VERSION_TIMEOUT_S,
) -> CliCapability:
    """Detect availability for one supported CLI."""
    path = resolve_cli_binary(name=name, which=which)
    if path is None or not is_runnable_candidate(path):
        return CliCapability(installed=False, path=None, version=None)

    probe = _probe_cli_version(path, timeout_s=version_timeout_s)
    if not probe.available:
        return CliCapability(installed=False, path=None, version=None)

    return CliCapability(installed=True, path=path, version=probe.version)


def detect_clis(
    *,
    which: Callable[[str], str | None] = shutil.which,
    version_timeout_s: float = DEFAULT_VERSION_TIMEOUT_S,
) -> dict[CliName, CliCapability]:
    """Detect local availability for every managed CLI."""
    return {
        name: detect_cli(name, which=which, version_timeout_s=version_timeout_s)
        for name in SUPPORTED_CLI_NAMES
    }
