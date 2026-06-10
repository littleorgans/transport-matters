"""Launch manifest lifecycle helpers."""

import contextlib
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from transport_matters import __version__
from transport_matters.lock import WorkspaceLock
from transport_matters.manifest import Manifest
from transport_matters.manifest import write as manifest_write
from transport_matters.workspace import run_root, workspace_id

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = ["run_with_workspace_manifest", "write_workspace_manifest"]


def run_with_workspace_manifest(
    *,
    working_dir: Path,
    storage_dir: Path,
    run_id: str,
    home_dir: Path | None = None,
    run_launch: Callable[[Callable[[int, int], None]], None],
) -> None:
    """Acquire the per-run lock, manage the manifest, and run the launch.

    The lock lives under the run directory ``{slug}/{hash}/{run_id}/``,
    not the shared workspace container. Each launch has a fresh ``run_id``,
    so the lock never contends: it is a per-run liveness beacon that
    ``instances`` / ``paths`` probe to tell a live run from a stale
    manifest, not a gate against a second instance in the same CWD.
    """
    wid = workspace_id(working_dir)
    run_dir = run_root(working_dir, run_id)
    with WorkspaceLock(run_dir) as wslock:

        def write_manifest_for(proxy_port: int, web_port: int) -> None:
            write_workspace_manifest(
                manifest_path=wslock.manifest_path,
                working_dir=working_dir,
                storage_dir=storage_dir,
                run_id=run_id,
                home_dir=home_dir,
                proxy_port=proxy_port,
                web_port=web_port,
                workspace_slug=wid.slug,
                workspace_hash=wid.hash,
            )

        try:
            run_launch(write_manifest_for)
        finally:
            with contextlib.suppress(FileNotFoundError):
                wslock.manifest_path.unlink()


def write_workspace_manifest(
    *,
    manifest_path: Path,
    working_dir: Path,
    storage_dir: Path,
    run_id: str,
    home_dir: Path | None,
    proxy_port: int,
    web_port: int | None,
    workspace_slug: str | None = None,
    workspace_hash: str | None = None,
) -> None:
    """Write the launch manifest with the existing field contract."""
    if workspace_slug is None or workspace_hash is None:
        wid = workspace_id(working_dir)
        workspace_slug = wid.slug
        workspace_hash = wid.hash
    manifest_write(
        manifest_path,
        Manifest(
            cwd=str(working_dir),
            pid=os.getpid(),
            proxy_port=proxy_port,
            web_port=web_port,
            storage_dir=str(storage_dir),
            run_id=run_id,
            started_at=datetime.now(UTC).isoformat(),
            transport_matters_version=__version__,
            slug=workspace_slug,
            hash=workspace_hash,
            home_dir=str(home_dir) if home_dir is not None else None,
        ),
    )
