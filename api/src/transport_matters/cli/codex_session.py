"""Managed-mint launch seam for codex (§5.2b).

`transport-matters codex` OWNS the codex rollout instead of guessing at it after the fact: it mints
the native session uuid, pre-seeds the minimal `session_meta` rollout at the exact path codex will
append to, and launches `codex resume <native>`. Owning the path kills the read-back tail RACE
(globbing for a file codex writes ~1s late) — any wire frame TM sees came from the codex it
launched, so TM always knows the uuid and the path (the old `locate` glob is deleted).

This module is pure I/O plumbing: it builds the path + minimal record and writes the seed. The
caller (`cli/codex_cmd.py`) resolves the codex sessions root (`home_seed.codex_sessions_root`),
mints the uuid, and threads the returned descriptor into the addon env + the resume argv.
"""

import json
import subprocess
import threading
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any  # Any: a provider-shaped session_meta record

from transport_matters.index.adapters.base import FileTailSource, encode_source_descriptor

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

# codex tags its rollout `session_meta.payload.originator`; the TUI value keeps the seeded session
# indistinguishable from a natively-started one when `codex resume` reloads it.
_ORIGINATOR = "codex-tui"
# Best-effort fallback when the codex binary cannot report its version (it is metadata in the
# rollout, not a resume gate); never let a version probe fail the launch.
_UNKNOWN_CODEX_VERSION = "0.0.0"


@dataclass(frozen=True, slots=True)
class _CodexCliVersionCacheKey:
    resolved_path: str
    mtime_ns: int


_CODEX_CLI_VERSION_LOCK = threading.Lock()
_CODEX_CLI_VERSION_CACHE: dict[_CodexCliVersionCacheKey, str] = {}


@dataclass(frozen=True, slots=True)
class CodexSessionSeed:
    """The launcher-owned codex session: the minted native uuid + the JSON ``source_descriptor`` of
    the rollout it seeded. The uuid drives ``codex resume``; the descriptor is stamped onto the
    session row so the tailer byte-tails the owned path (both flow to the addon via env)."""

    native_session_id: str
    source_descriptor: str


def codex_rollout_path(native_session_id: str, now: datetime, *, sessions_root: Path) -> Path:
    """The exact rollout path codex appends to for this session: matches codex's on-disk layout
    ``<sessions_root>/YYYY/MM/DD/rollout-<wallclock>-<uuid>.jsonl`` (verified on real rollouts)."""
    return (
        sessions_root
        / now.strftime("%Y/%m/%d")
        / f"rollout-{now.strftime('%Y-%m-%dT%H-%M-%S')}-{native_session_id}.jsonl"
    )


def build_session_meta(
    native_session_id: str, now: datetime, cwd: str, cli_version: str
) -> dict[str, Any]:
    """The minimal ``session_meta`` record `codex resume <uuid>` accepts (verified): the payload
    carries the id/timestamp/cwd/originator/cli_version codex restores the session from."""
    timestamp = now.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return {
        "timestamp": timestamp,
        "type": "session_meta",
        "payload": {
            "id": native_session_id,
            "timestamp": timestamp,
            "cwd": cwd,
            "originator": _ORIGINATOR,
            "cli_version": cli_version,
        },
    }


def seed_codex_session(
    *,
    native_session_id: str,
    now: datetime,
    working_dir: Path,
    cli_version: str,
    sessions_root: Path,
    home_dir: Path | None = None,
    write: bool = True,
) -> CodexSessionSeed:
    """Seed the owned rollout (one newline-terminated ``session_meta`` line) and return the binding
    seed. ``write=False`` (print-command dry run) computes the path/descriptor without touching disk.

    ``home_dir`` is the managed ``--agent-home-dir`` (when set), recorded EXPLICITLY on the descriptor so a
    §10.5 rebuild knows the codex home the rollout path resolved under without the live env; ``None``
    = codex's native home (``sessions_root`` is already ``<home>/sessions`` either way)."""
    path = codex_rollout_path(native_session_id, now, sessions_root=sessions_root)
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = build_session_meta(native_session_id, now, str(working_dir), cli_version)
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    descriptor = encode_source_descriptor(
        FileTailSource(
            path=str(path),
            format="codex_rollout",
            home_dir=str(home_dir) if home_dir is not None else None,
        )
    )
    return CodexSessionSeed(native_session_id=native_session_id, source_descriptor=descriptor)


def resolve_codex_cli_version(codex_path: str, *, run: Callable[..., Any] = subprocess.run) -> str:
    """Best-effort codex version from ``codex --version`` (``codex-cli 0.137.0`` → ``0.137.0``).

    The version is rollout metadata, not a resume gate, so any failure (missing binary, odd output)
    degrades to a sentinel rather than failing the launch."""
    cache_key = _codex_cli_version_cache_key(codex_path)
    if cache_key is None:
        return _run_codex_cli_version(codex_path, run=run)

    with _CODEX_CLI_VERSION_LOCK:
        cached = _CODEX_CLI_VERSION_CACHE.get(cache_key)
        if cached is not None:
            return cached
        version = _run_codex_cli_version(codex_path, run=run)
        _CODEX_CLI_VERSION_CACHE[cache_key] = version
        return version


def _codex_cli_version_cache_key(codex_path: str) -> _CodexCliVersionCacheKey | None:
    try:
        resolved = Path(codex_path).resolve(strict=True)
        stat = resolved.stat()
    except OSError:
        return None
    return _CodexCliVersionCacheKey(str(resolved), stat.st_mtime_ns)


def _run_codex_cli_version(codex_path: str, *, run: Callable[..., Any]) -> str:
    try:
        result = run(
            [codex_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except OSError, ValueError, subprocess.SubprocessError:
        return _UNKNOWN_CODEX_VERSION
    out = (getattr(result, "stdout", "") or "").strip()
    return out.split()[-1] if out else _UNKNOWN_CODEX_VERSION


def _reset_codex_cli_version_cache_for_tests() -> None:
    with _CODEX_CLI_VERSION_LOCK:
        _CODEX_CLI_VERSION_CACHE.clear()
