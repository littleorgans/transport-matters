"""Workspace identity for manicure multi-instance support.

A *workspace* is a CWD (canonicalized via ``Path.resolve``) at which a
``manicure start`` runs. Two terminals in the same workspace must collide
fast; different workspaces must coexist cleanly. Identity is derived
purely from the resolved path: a human-readable slug plus a short stable
hash.

Layout: ``~/.manicure/workspaces/{slug}/{hash}/``

- ``slug``: human-readable identifier from the last path segments.
  Collisions across distinct paths are resolved by the ``{hash}/``
  subdirectory, so the slug is a display aid, not the identity.
- ``hash``: ``blake2b(canonical.as_posix(), digest_size=4)`` as hex
  (8 chars). Stable for a given canonical path on a given machine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import blake2b
from pathlib import Path

__all__ = ["WorkspaceId", "workspace_id", "workspace_root", "workspace_storage"]


# How many tail path segments contribute to the slug. Three captures the
# common monorepo shape (``<org>/<repo>/<subdir>``) while staying well
# under the 40-char cap for typical repo names.
_SLUG_TAIL_SEGMENTS = 3
_SLUG_MAX_LEN = 40
_SLUG_ILLEGAL = re.compile(r"[^a-z0-9_-]+")
_SLUG_DASH_RUN = re.compile(r"-{2,}")


@dataclass(frozen=True, slots=True)
class WorkspaceId:
    """Stable identity for a working directory.

    ``root`` is the fully resolved CWD path. ``slug`` + ``hash`` form the
    on-disk workspace location under ``~/.manicure/workspaces/``.
    """

    slug: str
    hash: str
    root: Path


def workspace_id(cwd: Path) -> WorkspaceId:
    """Derive a stable :class:`WorkspaceId` from *cwd*.

    Canonicalises the path (follows symlinks; does not require the path
    to exist). Pure function modulo the stat calls ``Path.resolve``
    performs to resolve symlinks.
    """
    canonical = cwd.resolve(strict=False)
    slug = _slugify(canonical)
    hash_ = blake2b(canonical.as_posix().encode("utf-8"), digest_size=4).hexdigest()
    return WorkspaceId(slug=slug, hash=hash_, root=canonical)


def workspace_root(cwd: Path) -> Path:
    """Return the on-disk workspace directory for *cwd*.

    Does **not** create the directory. Callers that need it materialised
    should ``mkdir(parents=True, exist_ok=True)`` themselves.
    """
    wid = workspace_id(cwd)
    return Path.home() / ".manicure" / "workspaces" / wid.slug / wid.hash


def workspace_storage(cwd: Path) -> Path:
    """Return the per-workspace storage directory for *cwd*, creating it.

    Identical path to :func:`workspace_root` — the lock, the manifest,
    and the captured exchanges all live under the same ``{slug}/{hash}/``
    root so a single ``rm -rf`` on that directory wipes one workspace
    cleanly. The important side effect is the ``mkdir``: callers use the
    returned path as ``settings.storage_dir`` input, so it must exist by
    the time the addon's :class:`DiskStorageBackend` opens it.

    Deliberately bypasses :func:`manicure.config.get_settings` — that
    helper is ``@lru_cache``'d and reads ``MANICURE_STORAGE_DIR`` from
    the environment, which would either (a) lock in a stale path from a
    previous call or (b) feed its own output back to itself once the CLI
    sets the env var for the child process.
    """
    root = workspace_root(cwd)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _slugify(canonical: Path) -> str:
    """Collapse the last N path segments into a filesystem-safe slug.

    Returns ``"root"`` for paths that yield an empty slug after cleanup
    (``/``, all-punctuation trees, etc.).
    """
    # Path.parts on POSIX includes the leading "/" as its own element;
    # drop it so the tail slice is pure name segments.
    parts = [p for p in canonical.parts if p not in ("", "/")]
    tail = parts[-_SLUG_TAIL_SEGMENTS:]
    raw = "-".join(tail).lower()
    # Replace any run of illegal chars with a single dash, then collapse
    # accidental adjacent dashes (e.g. from a segment that already ended
    # in ``-``).
    cleaned = _SLUG_ILLEGAL.sub("-", raw)
    cleaned = _SLUG_DASH_RUN.sub("-", cleaned).strip("-")
    if not cleaned:
        return "root"
    # Left-truncate on overflow: the leaf (most specific) segment is the
    # part the user recognises, so we keep the right-hand end.
    if len(cleaned) > _SLUG_MAX_LEN:
        cleaned = cleaned[-_SLUG_MAX_LEN:].lstrip("-")
    return cleaned or "root"
