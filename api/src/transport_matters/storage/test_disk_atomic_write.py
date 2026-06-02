from pathlib import Path
from unittest.mock import patch

import pytest

from transport_matters.storage import test_disk as disk_tests
from transport_matters.storage.base import ExchangeArtifacts
from transport_matters.storage.disk import DiskStorageBackend


@pytest.fixture
def storage(tmp_path: str) -> DiskStorageBackend:
    return DiskStorageBackend(root=str(tmp_path))


class TestAtomicWrite:
    async def test_no_tmp_dir_after_successful_write(self, storage: DiskStorageBackend) -> None:
        """Successful write should leave no .tmp directories."""
        artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"test","max_tokens":1024}',
            request_ir=disk_tests._make_ir(),
        )

        await storage.write_exchange("atomic-001", artifacts)

        tmp_dirs = [d for d in storage.root.iterdir() if d.name.endswith(".tmp")]
        assert tmp_dirs == []

    async def test_crash_recovery_cleans_tmp_on_init(self, tmp_path: Path) -> None:
        """Leftover .tmp dirs from interrupted writes are cleaned up on init."""
        leftover = tmp_path / "20260101T000000Z-deadbeef.tmp"
        leftover.mkdir()
        (leftover / "request.raw").write_bytes(b"partial")

        DiskStorageBackend(root=str(tmp_path))

        assert not leftover.exists()
        normal = tmp_path / "20260101T000000Z-abcd1234"
        normal.mkdir()
        DiskStorageBackend(root=str(tmp_path))
        assert normal.exists()

    async def test_failed_write_cleans_up_tmp(self, storage: DiskStorageBackend) -> None:
        """If write_exchange fails mid-write, the .tmp dir is removed."""
        artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"test","max_tokens":1024}',
            request_ir=disk_tests._make_ir(),
        )

        with (
            patch("aiofiles.open", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            await storage.write_exchange("fail-001", artifacts)

        tmp_dirs = [d for d in storage.root.iterdir() if d.name.endswith(".tmp")]
        assert tmp_dirs == []

    async def test_rewrite_failure_restores_original_exchange_dir(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "rewrite-fail-001"
        original_ir = disk_tests._make_ir()
        await storage.write_exchange(
            exchange_id,
            ExchangeArtifacts(
                request_raw=b'{"model":"original","max_tokens":1024}',
                request_ir=original_ir,
            ),
        )

        original_dir = storage._find_exchange_dir(exchange_id)
        original_raw = (original_dir / "request.raw").read_bytes()
        original_rename = Path.rename

        def fail_final_rename(self: Path, target: Path) -> Path:
            if self.name.endswith(".tmp") and target == original_dir:
                raise OSError("rename failed")
            return original_rename(self, target)

        with (
            patch.object(Path, "rename", autospec=True, side_effect=fail_final_rename),
            pytest.raises(OSError, match="rename failed"),
        ):
            await storage.write_exchange(
                exchange_id,
                ExchangeArtifacts(
                    request_raw=b'{"model":"rewritten","max_tokens":2048}',
                    request_ir=original_ir,
                ),
            )

        restored_dir = storage._find_exchange_dir(exchange_id)
        assert restored_dir == original_dir
        assert (restored_dir / "request.raw").read_bytes() == original_raw
        assert not any(path.name.endswith(".tmp") for path in storage.root.iterdir())
