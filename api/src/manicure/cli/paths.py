"""The `manicure paths` resolution logic.

Split out from ``cli/__init__.py`` so the package entry point stays
under the 700-LOC invariant and this module can own the workspace
selector semantics (``--workspace slug-or-cwd``) in one place.

Resolution order for the ``storage`` value:

1. If the caller passes a selector, treat it as a path (when it
   contains a path separator or expands via ``~``) or a slug. Paths
   canonicalise via :func:`workspace_id`; slugs go through a manifest
   scan under ``~/.manicure/workspaces/{slug}/``.
2. Otherwise prefer ``MANICURE_CWD`` from the environment — so
   ``manicure paths`` invoked from a Claude session launched by
   ``manicure start`` targets the launching workspace even if the
   user has ``cd``'d into a subdirectory. Fall back to ``Path.cwd()``
   when the env var is absent (bare CLI invocation).
3. Once a target CWD or slug is known, prefer a live manifest's
   ``storage_dir`` (the user may have overridden it with
   ``start --storage-dir``); failing that, return
   :func:`workspace_root` (the default per-workspace root). Neither
   branch creates directories — ``paths`` is read-only.
"""

from __future__ import annotations

import json
import os
from importlib.resources import files
from pathlib import Path

import typer

from manicure import __version__
from manicure.lock import WorkspaceLock
from manicure.manifest import Manifest, read
from manicure.workspace import workspace_root

__all__ = ["resolve_paths"]


_WORKSPACES_DIRNAME = "workspaces"


def _workspaces_root() -> Path:
    """Return the shared `~/.manicure/workspaces/` directory."""
    return Path.home() / ".manicure" / _WORKSPACES_DIRNAME


def resolve_paths(*, workspace: str | None, as_json: bool) -> None:
    """Body of ``manicure paths``.

    Resolves the storage root per ``workspace`` (see module docstring),
    then renders the standard set of path entries as either JSON or an
    aligned two-column table.
    """
    package_root = Path(str(files("manicure")))
    addon_path = package_root / "addon.py"
    www_path = package_root / "www"
    storage = _resolve_storage(workspace)

    entries = {
        "version": __version__,
        "package": str(package_root),
        "addon": str(addon_path),
        "www": str(www_path),
        "storage": str(storage),
        "exchanges": str(storage / "exchanges"),
        "rules": str(storage / "rules.json"),
        "index": str(storage / "index.jsonl"),
    }

    if as_json:
        typer.echo(json.dumps(entries, indent=2))
        return

    width = max(len(k) for k in entries)
    for key, value in entries.items():
        typer.echo(f"  {key.ljust(width)}  {value}")


def _resolve_storage(selector: str | None) -> Path:
    """Return the storage path the entries should use.

    See the module docstring for the full resolution order.
    """
    if selector is None:
        # MANICURE_CWD wins over Path.cwd() so a paths lookup from a
        # Claude session spawned by ``manicure start`` resolves to the
        # launching workspace even if the user has since ``cd``'d into
        # a subdirectory. Empty string is treated as unset.
        env_cwd = os.environ.get("MANICURE_CWD") or None
        return _storage_for_cwd(Path(env_cwd) if env_cwd else Path.cwd())

    # A path-shaped selector goes through CWD resolution; a bare token
    # is a slug. ``os.sep`` handles both POSIX and Windows uniformly,
    # and ``~`` catches the common home-relative case on any platform.
    if os.sep in selector or selector.startswith("~"):
        return _storage_for_cwd(Path(selector).expanduser())

    return _storage_for_slug(selector)


def _storage_for_cwd(cwd: Path) -> Path:
    """Return the storage path for *cwd*.

    Live manifest wins (it may point at a user-overridden storage dir
    from ``start --storage-dir``). Otherwise return the default
    per-workspace root via :func:`workspace_root`.
    """
    ws_root = workspace_root(cwd)
    manifest = _live_manifest(ws_root)
    if manifest is not None:
        return Path(manifest.storage_dir)
    return ws_root


def _storage_for_slug(slug: str) -> Path:
    """Resolve a slug to a storage path via manifest scan.

    A slug is a display aid; the on-disk identity is
    ``{slug}/{hash}/``, so multiple workspaces can share a slug when
    two distinct CWDs happen to collapse to the same tail. We accept
    any manifest under ``{slug}/*/manifest.json`` (live or stale, so
    users can inspect a recently-exited instance's paths) but fail
    loudly on ambiguity.
    """
    root = _workspaces_root() / slug
    candidates: list[tuple[Path, Manifest]] = []
    if root.is_dir():
        for hash_dir in sorted(root.iterdir()):
            if not hash_dir.is_dir():
                continue
            m = read(hash_dir / "manifest.json")
            if m is not None:
                candidates.append((hash_dir, m))

    if not candidates:
        typer.secho(
            f"error: no workspace matching {slug!r}.",
            fg=typer.colors.RED,
            err=True,
        )
        typer.echo(
            "Run `manicure list` to see live workspaces, or pass a directory path.",
            err=True,
        )
        raise typer.Exit(2)
    if len(candidates) > 1:
        typer.secho(
            f"error: slug {slug!r} matches {len(candidates)} workspaces.",
            fg=typer.colors.RED,
            err=True,
        )
        for _hash_dir, m in candidates:
            typer.echo(f"  {m.slug}/{m.hash}  cwd={m.cwd}", err=True)
        typer.echo(
            "Disambiguate by passing the CWD path to --workspace instead.",
            err=True,
        )
        raise typer.Exit(2)
    return Path(candidates[0][1].storage_dir)


def _live_manifest(ws_root: Path) -> Manifest | None:
    """Return the manifest at *ws_root* if a live instance holds the lock.

    Returns ``None`` when the manifest is missing, malformed, or the
    sibling lock is not currently held (i.e. stale manifest from a
    crashed instance). ``paths`` is read-only, so we never reap stale
    manifests here — ``manicure list`` handles that.
    """
    m = read(ws_root / "manifest.json")
    if m is None:
        return None
    if WorkspaceLock.is_held(ws_root):
        return m
    return None
