"""Workspace instance helpers for list output and contention UX.

Split out from ``cli/__init__.py`` so the package entry point stays
under the 700-LOC invariant. Callers in ``__init__`` re-export the
public helpers at ``transport_matters.cli.X`` when they're candidates for
monkeypatching in tests; private helpers stay pinned here.
"""

import contextlib
import json
from typing import TYPE_CHECKING

import typer

from transport_matters.lock import WorkspaceLock
from transport_matters.manifest import Manifest, read_all
from transport_matters.storage_roots import default_workspaces_root

from .identity import PRODUCT_LABEL

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["_list_instances"]


_TABLE_HEADERS: tuple[str, ...] = (
    "WORKSPACE",
    "RUN",
    "PID",
    "PROXY",
    "WEB",
    "STORAGE",
    "STARTED",
)

# Runs are keyed by a UUID; the leading block is enough to disambiguate
# the handful of instances a user runs in one CWD without a 36-char column.
_RUN_ID_DISPLAY_LEN = 8


def _list_instances(*, as_json: bool) -> None:
    """Body of ``transport-matters list``.

    Scans ``~/.transport-matters/workspaces/``, probes each manifest's lock via
    :meth:`WorkspaceLock.is_held`, reaps stale manifests, and prints
    the live ones as a table or JSON.
    """
    root = default_workspaces_root()
    manifests = read_all(root)
    live: list[Manifest] = []
    for m in manifests:
        run_dir = root / m.slug / m.hash / m.run_id
        if WorkspaceLock.is_held(run_dir):
            live.append(m)
        else:
            _reap(run_dir)

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
        "run_id": m.run_id,
        "cwd": m.cwd,
        "pid": m.pid,
        "proxy_port": m.proxy_port,
        "web_port": m.web_port,
        "storage_dir": m.storage_dir,
        "started_at": m.started_at,
        "transport_matters_version": m.transport_matters_version,
    }


def _reap(run_dir: Path) -> None:
    """Remove the stale manifest for a dead run.

    Silent by design: best-effort cleanup during ``transport-matters list``.

    Only the manifest is unlinked. The run directory also holds the run's
    captured exchanges (``index.jsonl``, ``exchanges/``) when storage is
    the default per-run root, and that history must survive the process
    that recorded it — so reaping clears the liveness advertisement, never
    the data. The ``lock`` file is left in place too: it is harmless, and
    no future ``start`` reuses this directory because each launch mints a
    fresh ``run_id``.
    """
    with contextlib.suppress(FileNotFoundError):
        (run_dir / "manifest.json").unlink()


def _print_table(manifests: list[Manifest]) -> None:
    """Render *manifests* as an aligned ASCII table."""
    rows: list[tuple[str, ...]] = [
        (
            m.slug,
            m.run_id[:_RUN_ID_DISPLAY_LEN],
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
