from __future__ import annotations

import json
from typing import TYPE_CHECKING

from transport_matters.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from pathlib import Path


class TestLegacyFlatAnchorCacheInvalidation:
    """Startup drops cache roots with legacy top-level flat anchor keys."""

    def test_wipes_root_when_index_contains_legacy_flat_anchor_keys(
        self, tmp_path: Path
    ) -> None:
        index_path = tmp_path / "index.jsonl"
        index_path.write_text(
            json.dumps(
                {
                    "id": "ex-legacy",
                    "track_spawn_exchange_id": "ex-parent",
                    "track_spawn_tool_use_id": "toolu_child",
                    "track_spawn_order": 0,
                }
            )
            + "\n"
        )
        sibling = tmp_path / "20250101T000000Z-deadbeef"
        sibling.mkdir()
        (sibling / "request.raw").write_bytes(b"stale")

        DiskStorageBackend(root=str(tmp_path))

        assert not index_path.exists()
        assert not sibling.exists()
        assert tmp_path.exists()

    def test_preserves_root_when_index_uses_nested_spawn_anchor(
        self, tmp_path: Path
    ) -> None:
        index_path = tmp_path / "index.jsonl"
        index_path.write_text(
            json.dumps(
                {
                    "id": "ex-new",
                    "spawn_anchor": {
                        "track_spawn_exchange_id": "ex-parent",
                        "track_spawn_tool_use_id": "toolu_child",
                        "track_spawn_order": 0,
                    },
                }
            )
            + "\n"
        )

        DiskStorageBackend(root=str(tmp_path))

        assert index_path.exists()

    def test_noop_when_index_missing(self, tmp_path: Path) -> None:
        sibling = tmp_path / "keep-me"
        sibling.mkdir()

        DiskStorageBackend(root=str(tmp_path))

        assert sibling.exists()

    def test_skips_malformed_lines_and_still_detects_legacy(
        self, tmp_path: Path
    ) -> None:
        index_path = tmp_path / "index.jsonl"
        index_path.write_text(
            "not json\n"
            "\n" + json.dumps({"id": "ex-legacy", "track_spawn_order": 0}) + "\n"
        )

        DiskStorageBackend(root=str(tmp_path))

        assert not index_path.exists()
