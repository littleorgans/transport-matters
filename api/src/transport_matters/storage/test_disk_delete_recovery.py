import shutil
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import patch

import pytest

from transport_matters.storage import test_disk as disk_tests
from transport_matters.storage.base import ExchangeArtifacts
from transport_matters.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def storage(tmp_path: str) -> DiskStorageBackend:
    return DiskStorageBackend(root=str(tmp_path))


async def test_directory_cleanup_failure_restores_index_row_and_artifacts(
    storage: DiskStorageBackend,
) -> None:
    exchange_id = "deadbeef-cleanup"
    entry = disk_tests._make_index_entry(exchange_id)
    artifacts = ExchangeArtifacts(request_raw=b"{}", request_ir=disk_tests._make_ir())
    await storage.append_index(entry)
    await storage.write_exchange(exchange_id, artifacts)
    exchange_dir = storage._find_exchange_dir(exchange_id)
    staged_dir = exchange_dir.parent / f"{exchange_dir.name}.del"
    original_run_io = storage._run_io

    async def fail_delete(func: object, *args: object) -> object:
        if func is shutil.rmtree and args and args[0] == staged_dir:
            raise OSError("delete cleanup failed")
        return await original_run_io(cast("Any", func), *args)

    with (
        patch.object(storage, "_run_io", side_effect=fail_delete),
        pytest.raises(OSError, match="delete cleanup failed"),
    ):
        await storage.delete_exchange(exchange_id)

    restored = await storage.read_index_entry(exchange_id)
    assert restored == entry
    restored_artifacts = await storage.read_exchange(exchange_id)
    assert restored_artifacts.request_raw == artifacts.request_raw
    assert not staged_dir.exists()


async def test_init_restores_staged_delete_when_index_row_still_present(
    storage: DiskStorageBackend, tmp_path: Path
) -> None:
    exchange_id = "deadbeef-init-restore"
    entry = disk_tests._make_index_entry(exchange_id)
    artifacts = ExchangeArtifacts(request_raw=b"{}", request_ir=disk_tests._make_ir())
    await storage.persist_exchange(entry, artifacts)
    exchange_dir = storage._find_exchange_dir(exchange_id)
    staged_dir = exchange_dir.parent / f"{exchange_dir.name}.del"
    exchange_dir.rename(staged_dir)

    fresh = DiskStorageBackend(root=str(tmp_path))

    restored = await fresh.read_index_entry(exchange_id)
    assert restored == entry
    assert fresh._find_exchange_dir(exchange_id) == exchange_dir
    assert not staged_dir.exists()


async def test_init_finalizes_staged_delete_when_index_row_missing(
    storage: DiskStorageBackend, tmp_path: Path
) -> None:
    exchange_id = "deadbeef-init-finalize"
    await storage.persist_exchange(
        disk_tests._make_index_entry(exchange_id),
        ExchangeArtifacts(request_raw=b"{}", request_ir=disk_tests._make_ir()),
    )
    exchange_dir = storage._find_exchange_dir(exchange_id)
    staged_dir = exchange_dir.parent / f"{exchange_dir.name}.del"
    exchange_dir.rename(staged_dir)
    (storage.root / "index.jsonl").write_text("", encoding="utf-8")

    fresh = DiskStorageBackend(root=str(tmp_path))

    assert await fresh.read_index_entry(exchange_id) is None
    assert not staged_dir.exists()
    with pytest.raises(FileNotFoundError):
        fresh._find_exchange_dir(exchange_id)
