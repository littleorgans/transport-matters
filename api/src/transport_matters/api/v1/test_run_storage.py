"""Tests for run scoped storage resolution helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from transport_matters.api.v1 import run_storage

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_disk_storage_backend_cache_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[Path] = []

    class FakeDiskStorageBackend:
        def __init__(self, root: Path) -> None:
            created.append(root)

    monkeypatch.setattr(run_storage, "DiskStorageBackend", FakeDiskStorageBackend)
    run_storage._disk_storage_for.cache_clear()
    try:
        for index in range(run_storage.RUN_STORAGE_BACKEND_CACHE_MAXSIZE + 1):
            run_storage._disk_storage_for(tmp_path / f"storage-{index}")

        assert run_storage._disk_storage_for.cache_info().currsize == (
            run_storage.RUN_STORAGE_BACKEND_CACHE_MAXSIZE
        )

        run_storage._disk_storage_for(tmp_path / "storage-0")
        assert len(created) == run_storage.RUN_STORAGE_BACKEND_CACHE_MAXSIZE + 2
    finally:
        run_storage._disk_storage_for.cache_clear()
