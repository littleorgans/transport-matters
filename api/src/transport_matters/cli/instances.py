"""Workspace instance helpers for list output and contention UX.

Split out from ``cli/__init__.py`` so the package entry point stays
under the 700-LOC invariant. Callers in ``__init__`` re-export the
public helpers at ``transport_matters.cli.X`` when they're candidates for
monkeypatching in tests; private helpers stay pinned here.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

import typer

from transport_matters.lock import WorkspaceLock, WorkspaceLocked
from transport_matters.manifest import Manifest, read, read_all

from .identity import PRODUCT_LABEL
from .net import loopback_http_url

__all__ = ["_list_instances", "_print_contention_error"]


_WORKSPACES_DIRNAME = "workspaces"
_TABLE_HEADERS: tuple[str, ...] = (
    "WORKSPACE",
    "PID",
    "PROXY",
    "WEB",
    "STORAGE",
    "STARTED",
)


def _workspaces_root() -> Path:
    """Return the workspaces directory under the user's home."""
    return Path.home() / ".manicure" / _WORKSPACES_DIRNAME


def _print_contention_error(exc: WorkspaceLocked, working_dir: Path) -> None:
    """Render a human-readable error for a live workspace.

    Reads the sibling manifest via :func:`transport_matters.manifest.read` so
    the error surfaces the live PID + ports. Missing/malformed manifests
    fall back to pointing at the lock path.
    """
    existing = read(exc.manifest_path)
    typer.secho(
        f"error: another {PRODUCT_LABEL} instance is already live in this workspace.",
        fg=typer.colors.RED,
        err=True,
    )
    typer.echo(f"  cwd: {working_dir}", err=True)
    if existing is not None:
        typer.echo("", err=True)
        typer.echo(f"  pid       {existing.pid}", err=True)
        typer.echo(
            f"  proxy     {loopback_http_url(existing.proxy_port)}",
            err=True,
        )
        typer.echo(
            f"  web       {loopback_http_url(existing.web_port)}",
            err=True,
        )
        typer.echo(f"  started   {existing.started_at}", err=True)
    else:
        typer.echo(f"  lock      {exc.lock_path}", err=True)
    typer.echo("", err=True)
    typer.echo(
        "If that process is no longer running, the lock releases on its own.\n"
        f"Otherwise stop the running instance, or start {PRODUCT_LABEL} from a\n"
        "different directory.",
        err=True,
    )


def _list_instances(*, as_json: bool) -> None:
    """Body of ``transport-matters list``.

    Scans ``~/.manicure/workspaces/``, probes each manifest's lock via
    :meth:`WorkspaceLock.is_held`, reaps stale manifests, and prints
    the live ones as a table or JSON.
    """
    root = _workspaces_root()
    manifests = read_all(root)
    live: list[Manifest] = []
    for m in manifests:
        ws_dir = root / m.slug / m.hash
        if WorkspaceLock.is_held(ws_dir):
            live.append(m)
        else:
            _reap(ws_dir)

    if as_json:
        typer.echo(
            json.dumps([_manifest_to_dict(m) for m in live], indent=2),
        )
        return

    if not live:
        typer.echo(f"no live {PRODUCT_LABEL} instances")
        return

    _print_table(live)


def _manifest_to_dict(m: Manifest) -> dict[str, object]:
    """Serialise a manifest for JSON output."""
    return {
        "slug": m.slug,
        "hash": m.hash,
        "cwd": m.cwd,
        "pid": m.pid,
        "proxy_port": m.proxy_port,
        "web_port": m.web_port,
        "storage_dir": m.storage_dir,
        "started_at": m.started_at,
        "manicure_version": m.manicure_version,
    }


def _reap(ws_dir: Path) -> None:
    """Remove the stale manifest for a dead workspace.

    Silent by design: best-effort cleanup during ``transport-matters list``.

    Only the manifest is unlinked — the ``lock`` file stays in place.
    Unlinking the lock would race with a concurrent ``start`` that has
    already opened the file and taken the flock: our unlink removes the
    dentry while the live instance's fd keeps the inode alive, and the
    next ``start`` re-creates the path via ``O_CREAT`` → a fresh inode,
    a successful flock, two processes sharing a workspace. Leaving the
    empty lock file alone is semantically harmless — the next ``start``
    re-opens the same inode and flocks it cleanly.
    """
    with contextlib.suppress(FileNotFoundError):
        (ws_dir / "manifest.json").unlink()


def _print_table(manifests: list[Manifest]) -> None:
    """Render *manifests* as an aligned ASCII table."""
    rows: list[tuple[str, ...]] = [
        (
            m.slug,
            str(m.pid),
            str(m.proxy_port),
            str(m.web_port),
            m.storage_dir,
            m.started_at,
        )
        for m in manifests
    ]
    all_rows: list[tuple[str, ...]] = [_TABLE_HEADERS, *rows]
    widths = [max(len(row[i]) for row in all_rows) for i in range(len(_TABLE_HEADERS))]
    for row in all_rows:
        typer.echo("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
