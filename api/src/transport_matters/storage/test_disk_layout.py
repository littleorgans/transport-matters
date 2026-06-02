from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from transport_matters.storage.disk_layout import DiskStorageLayout


def test_default_root_uses_transport_matters_storage_root() -> None:
    layout = DiskStorageLayout()

    assert layout.root == Path.home() / ".transport-matters"


def test_exchange_dir_uses_existing_timestamp_and_short_id_format(
    tmp_path: Path,
) -> None:
    layout = DiskStorageLayout(tmp_path)

    exchange_dir = layout.new_exchange_dir(
        "abcdef01-1234",
        now=datetime(2025, 6, 1, 12, 0, tzinfo=UTC),
    )

    assert exchange_dir == tmp_path / "20250601T120000Z-abcdef01"
    assert (
        layout.exchange_dir_name(
            "abcdef01-1234",
            ts=datetime(2025, 6, 1, 12, 0, tzinfo=UTC),
        )
        == exchange_dir.name
    )
    assert layout.exchange_index_path_for(
        "abcdef01-1234",
        ts=datetime(2025, 6, 1, 12, 0, tzinfo=UTC),
    ) == layout.exchange_index_path(exchange_dir.name)


def test_short_id_helpers_keep_exchange_id_and_dir_name_semantics(
    tmp_path: Path,
) -> None:
    layout = DiskStorageLayout(tmp_path)

    assert layout.short_id("abcdef01-1234") == "abcdef01"
    assert layout.short_id_from_dir_name("20250601T120000Z-abcdef01") == "abcdef01"


def test_artifact_paths_keep_existing_filenames(tmp_path: Path) -> None:
    layout = DiskStorageLayout(tmp_path)
    exchange_dir = tmp_path / "20250601T120000Z-abcdef01"

    paths = layout.artifact_paths(exchange_dir)

    assert paths.entry == exchange_dir / "entry.json"
    assert paths.request_raw == exchange_dir / "request.raw"
    assert paths.request_ir == exchange_dir / "request.ir.json"
    assert paths.request_curated_raw == exchange_dir / "request.curated.raw"
    assert paths.request_curated_ir == exchange_dir / "request.curated.ir.json"
    assert paths.request_audit == exchange_dir / "request.audit.json"
    assert paths.response_raw == exchange_dir / "response.raw"
    assert paths.response_ir == exchange_dir / "response.ir.json"
    assert paths.transport == exchange_dir / "transport.json"
    assert paths.events == exchange_dir / "events.jsonl"
    assert paths.turn == exchange_dir / "turn.json"


def test_exchange_suffix_paths_keep_existing_names(tmp_path: Path) -> None:
    layout = DiskStorageLayout(tmp_path)
    exchange_dir = tmp_path / "20250601T120000Z-abcdef01"

    assert layout.index_path == tmp_path / "index.jsonl"
    assert layout.index_tmp_path == tmp_path / "index.jsonl.tmp"
    assert layout.tmp_exchange_dir(exchange_dir) == tmp_path / ("20250601T120000Z-abcdef01.tmp")
    assert layout.backup_exchange_dir(exchange_dir) == tmp_path / ("20250601T120000Z-abcdef01.bak")
    assert layout.staged_delete_dir(exchange_dir) == tmp_path / ("20250601T120000Z-abcdef01.del")
    assert layout.exchange_index_path(exchange_dir.name) == ("exchanges/20250601T120000Z-abcdef01/")
