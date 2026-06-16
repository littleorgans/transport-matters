"""Run scoped disk storage resolution for v1 API routes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

from fastapi import HTTPException, Request
from fastapi import status as http_status

from transport_matters.config import get_settings
from transport_matters.manifest import read_all as read_manifests
from transport_matters.run_manager import RunManager, RunNotFoundError
from transport_matters.storage import get_storage
from transport_matters.storage.disk import DiskStorageBackend
from transport_matters.storage_roots import default_workspaces_root
from transport_matters.workspace import workspace_id

if TYPE_CHECKING:
    from transport_matters.storage import StorageBackend


_BACKENDS_BY_STORAGE_DIR: dict[Path, StorageBackend] = {}


@dataclass(frozen=True, slots=True)
class RunStorageContext:
    run_id: str
    cwd: Path
    storage_dir: Path
    storage: StorageBackend


class RunStorageNotFoundError(KeyError):
    """Raised when no run metadata can resolve a storage backend."""


async def resolve_run_storage(request: Request, run_id: str) -> RunStorageContext:
    """Resolve a run's disk storage from live or persisted run metadata."""
    live = _live_run_storage(request, run_id)
    if live is not None:
        return live

    current = await _current_process_run_storage(run_id)
    if current is not None:
        return current

    manifest = await _manifest_run_storage(run_id)
    if manifest is not None:
        return manifest

    raise RunStorageNotFoundError(run_id)


async def resolve_run_storage_or_404(request: Request, run_id: str) -> RunStorageContext:
    try:
        return await resolve_run_storage(request, run_id)
    except RunStorageNotFoundError as exc:
        _run_not_found(run_id, exc)


def run_workspace_id(context: RunStorageContext) -> str:
    wid = workspace_id(context.cwd)
    return f"{wid.slug}/{wid.hash}"


def _live_run_storage(request: Request, run_id: str) -> RunStorageContext | None:
    manager = getattr(request.app.state, "run_manager", None)
    if not isinstance(manager, RunManager):
        return None
    try:
        run = manager.get(run_id)
    except RunNotFoundError:
        return None
    return _context(
        run_id=run_id,
        cwd=run.cwd,
        storage_dir=run.spawn_spec.storage_dir,
    )


async def _current_process_run_storage(run_id: str) -> RunStorageContext | None:
    settings = get_settings()
    if settings.run_id != run_id:
        return None
    cwd = (settings.cwd or Path.cwd()).resolve()
    return _context(
        run_id=run_id,
        cwd=cwd,
        storage_dir=settings.storage_dir,
        storage=await get_storage(),
    )


async def _manifest_run_storage(run_id: str) -> RunStorageContext | None:
    for manifest in read_manifests(default_workspaces_root()):
        if manifest.run_id == run_id:
            storage_dir = _resolve_path(Path(manifest.storage_dir))
            storage = None
            if _resolve_path(get_settings().storage_dir) == storage_dir:
                storage = await get_storage()
            return _context(
                run_id=run_id,
                cwd=Path(manifest.cwd),
                storage_dir=storage_dir,
                storage=storage,
            )
    return None


def _context(
    *,
    run_id: str,
    cwd: Path,
    storage_dir: Path,
    storage: StorageBackend | None = None,
) -> RunStorageContext:
    resolved_storage_dir = _resolve_path(storage_dir)
    return RunStorageContext(
        run_id=run_id,
        cwd=_resolve_path(cwd),
        storage_dir=resolved_storage_dir,
        storage=storage or _disk_storage_for(resolved_storage_dir),
    )


def _resolve_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _disk_storage_for(storage_dir: Path) -> StorageBackend:
    backend = _BACKENDS_BY_STORAGE_DIR.get(storage_dir)
    if backend is None:
        backend = DiskStorageBackend(root=storage_dir)
        _BACKENDS_BY_STORAGE_DIR[storage_dir] = backend
    return backend


def _run_not_found(run_id: str, exc: BaseException) -> NoReturn:
    raise HTTPException(
        status_code=http_status.HTTP_404_NOT_FOUND,
        detail={
            "code": "run_not_found",
            "message": f"Run {run_id} not found",
        },
    ) from exc
