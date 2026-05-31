"""Transport Matters workspace manifest, advisory sidecar next to the lock.

The manifest is *advisory*. Truth is the lock file's ``flock`` state.
Callers must never treat a present manifest as proof that a process is
alive; they must probe the sibling ``lock`` with
``fcntl.flock(LOCK_EX | LOCK_NB)`` before reporting liveness.

On-disk layout (per run)::

    ~/.transport-matters/workspaces/{slug}/{hash}/{run_id}/
        lock                # fcntl.flock target (held by live instance)
        manifest.json       # this file — metadata about the live instance

The ``{slug}/{hash}/`` container is shared by every run launched from one
CWD; each run owns a ``{run_id}/`` subdirectory, so two instances in the
same CWD never collide.

Schema is a simple JSON object; fields mirror the :class:`Manifest`
dataclass. ``read`` tolerates missing, malformed, and schema-mismatched
files by returning ``None`` so callers can reap them transparently.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["Manifest", "read", "read_all", "write"]


@dataclass(frozen=True, slots=True)
class Manifest:
    """Advisory metadata for a live Transport Matters instance.

    Fields mirror the JSON on disk. All values are primitive so
    ``dataclasses.asdict`` produces a JSON-serialisable dict.
    """

    cwd: str
    pid: int
    proxy_port: int
    web_port: int
    storage_dir: str
    run_id: str
    started_at: str
    transport_matters_version: str
    slug: str
    hash: str
    home_dir: str | None = None


def write(path: Path, manifest: Manifest) -> None:
    """Write *manifest* to *path* atomically.

    Creates ``path.parent`` if missing. Uses ``os.replace`` so concurrent
    readers never observe a partial file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Scope the tempfile name with our PID so another process
    # racing on a sibling workspace will not collide on the temp name.
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
    tmp.replace(path)


def read(path: Path) -> Manifest | None:
    """Return the :class:`Manifest` at *path*, or ``None`` on any failure.

    A missing file, a malformed JSON body, or a schema mismatch all
    return ``None`` so callers can treat the manifest as advisory and
    move on without crashing.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (
        FileNotFoundError,
        IsADirectoryError,
        NotADirectoryError,
        PermissionError,
    ):
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return Manifest(**data)
    except TypeError:
        # Missing required fields or unexpected keys — treat as stale.
        return None


def read_all(root: Path) -> list[Manifest]:
    """Return every readable manifest under *root*.

    Scans ``root/*/*/*/manifest.json`` (the ``{slug}/{hash}/{run_id}/``
    layout). Unreadable or malformed manifests are skipped silently —
    they'll be reaped by the next ``transport-matters list`` that lands on
    their lock.
    """
    if not root.is_dir():
        return []
    manifests: list[Manifest] = []
    for manifest_path in root.glob("*/*/*/manifest.json"):
        m = read(manifest_path)
        if m is not None:
            manifests.append(m)
    return manifests
