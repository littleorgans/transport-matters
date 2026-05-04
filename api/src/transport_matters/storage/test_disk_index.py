from __future__ import annotations

import pytest

from transport_matters.storage import test_disk as disk_tests
from transport_matters.storage.base import IndexEntry, ResStats, SpawnAnchor
from transport_matters.storage.disk import DiskStorageBackend


@pytest.fixture
def storage(tmp_path: str) -> DiskStorageBackend:
    return DiskStorageBackend(root=str(tmp_path))


class TestAppendAndReadIndex:
    async def test_append_and_read(self, storage: DiskStorageBackend) -> None:
        entry = disk_tests._make_index_entry()
        await storage.append_index(entry)
        entries = await storage.read_index(limit=10, offset=0)
        assert len(entries) == 1
        assert entries[0].id == "ex-001"

    async def test_read_empty(self, storage: DiskStorageBackend) -> None:
        entries = await storage.read_index(limit=10, offset=0)
        assert entries == []

    async def test_pagination(self, storage: DiskStorageBackend) -> None:
        for i in range(5):
            await storage.append_index(disk_tests._make_index_entry(f"ex-{i:03d}"))
        page = await storage.read_index(limit=2, offset=1)
        assert len(page) == 2
        assert page[0].id == "ex-001"
        assert page[1].id == "ex-002"

    async def test_upsert_replaces_existing_row(
        self, storage: DiskStorageBackend
    ) -> None:
        original = disk_tests._make_index_entry("ex-upsert")
        await storage.append_index(original)

        updated = original.model_copy(
            update={"res": ResStats(stop_reason="completed", text_chars=12)}
        )
        await storage.upsert_index(updated)

        entries = await storage.read_index(limit=10, offset=0)
        assert len(entries) == 1
        assert entries[0].id == "ex-upsert"
        assert entries[0].res is not None
        assert entries[0].res.stop_reason == "completed"

    async def test_track_fields_round_trip(self, storage: DiskStorageBackend) -> None:
        entry = disk_tests._make_index_entry("ex-001").model_copy(
            update={
                "track_id": "toolu_child",
                "parent_track_id": "run-root",
                "track_display_name": "worker",
                "track_role": "subagent",
                "spawn_anchor": SpawnAnchor(
                    track_spawn_exchange_id="ex-parent",
                    track_spawn_tool_use_id="toolu_child",
                    track_spawn_order=0,
                ),
            }
        )

        await storage.append_index(entry)

        entries = await storage.read_index(limit=10, offset=0)
        assert entries[0].track_id == "toolu_child"
        assert entries[0].parent_track_id == "run-root"
        assert entries[0].track_display_name == "worker"
        assert entries[0].track_role == "subagent"
        assert entries[0].spawn_anchor is not None
        assert entries[0].spawn_anchor.track_spawn_exchange_id == "ex-parent"
        assert entries[0].spawn_anchor.track_spawn_tool_use_id == "toolu_child"
        assert entries[0].spawn_anchor.track_spawn_order == 0
        dumped = entries[0].model_dump(mode="json")
        assert dumped["spawn_anchor"] == {
            "track_spawn_exchange_id": "ex-parent",
            "track_spawn_tool_use_id": "toolu_child",
            "track_spawn_order": 0,
        }
        assert "track_spawn_exchange_id" not in dumped
        assert "track_spawn_tool_use_id" not in dumped
        assert "track_spawn_order" not in dumped

    async def test_null_spawn_anchor_round_trips(
        self, storage: DiskStorageBackend
    ) -> None:
        entry = disk_tests._make_index_entry("ex-001").model_copy(
            update={"spawn_anchor": None}
        )

        await storage.append_index(entry)

        entries = await storage.read_index(limit=10, offset=0)
        assert entries[0].spawn_anchor is None
        assert entries[0].model_dump(mode="json")["spawn_anchor"] is None

    def test_entry_defaults_to_root_track(self) -> None:
        entry = IndexEntry.model_validate(
            disk_tests._make_index_entry("ex-001").model_dump()
        )

        assert entry.track_id == entry.run_id
        assert entry.parent_track_id is None
        assert entry.track_display_name is None
        assert entry.track_role == "parent"
        assert entry.spawn_anchor is None

    def test_spawn_order_rejects_negative_values(self) -> None:
        payload = disk_tests._make_index_entry("ex-001").model_dump()
        payload["spawn_anchor"] = {
            "track_spawn_exchange_id": "ex-parent",
            "track_spawn_tool_use_id": "toolu_child",
            "track_spawn_order": -1,
        }

        with pytest.raises(ValueError):
            IndexEntry.model_validate(payload)
