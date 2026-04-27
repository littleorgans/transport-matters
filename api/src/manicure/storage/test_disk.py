"""Tests for the disk storage backend.

Uses ``tmp_path`` to avoid touching the real filesystem.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from manicure.codex.derivation import CODEX_DERIVATION_VERSION
from manicure.codex.events import (
    CodexDerivationCursor,
    CodexOpenAssistantItem,
    CodexSemanticEvent,
    CodexTransportRef,
    CodexTurnSummary,
)
from manicure.ir import (
    InternalRequest,
    InternalResponse,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
    UsageStats,
)
from manicure.overrides import OverrideAudit, OverrideAuditEntry
from manicure.storage.base import (
    ExchangeArtifacts,
    IndexEntry,
    ReqStats,
    ResStats,
    SpawnAnchor,
)
from manicure.storage.disk import DiskStorageBackend


@pytest.fixture
def storage(tmp_path: str) -> DiskStorageBackend:
    return DiskStorageBackend(root=str(tmp_path))


def _make_ir() -> InternalRequest:
    return InternalRequest(
        model="anthropic/claude-sonnet-4-20250514",
        provider="anthropic",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hi")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


def _make_index_entry(entry_id: str = "ex-001") -> IndexEntry:
    return IndexEntry(
        id=entry_id,
        ts=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        provider="anthropic",
        model="anthropic/claude-sonnet-4-20250514",
        path="/v1/messages",
        req=ReqStats(
            system_parts=0,
            system_chars=0,
            tools_count=0,
            tools_chars=0,
            messages_count=1,
            messages_chars=2,
            total_chars=2,
        ),
    )


def _make_audit() -> OverrideAudit:
    return OverrideAudit(
        entries=[
            OverrideAuditEntry(
                kind="system_part_text",
                target="system:0",
                applied=True,
                chars_delta=-3,
                curated_value="patched",
            )
        ],
        chars_before=10,
        chars_after=7,
    )


def _make_codex_event(event_id: str = "evt_000001") -> CodexSemanticEvent:
    return CodexSemanticEvent(
        event_id=event_id,
        exchange_id="codex-exchange-001",
        session_id="ws_123",
        turn_id="turn_001",
        seq=1,
        ts=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
        source="client",
        kind="turn_started",
        transport_ref=CodexTransportRef(message_index=0),
        derivation_version=CODEX_DERIVATION_VERSION,
    )


def _make_open_turn() -> CodexTurnSummary:
    return CodexTurnSummary(
        turn_id="turn_001",
        exchange_id="codex-exchange-001",
        session_id="ws_123",
        turn_index=0,
        request_message_index=0,
        message_range_start=0,
        message_range_end=0,
        model="codex/gpt-5-codex",
        status="open",
        text_chars=12,
        tool_calls=0,
        started_at=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
        derivation_version=CODEX_DERIVATION_VERSION,
        cursor=CodexDerivationCursor(
            next_message_index=1,
            next_seq=2,
            open_assistant_items={
                "msg_01": CodexOpenAssistantItem(text="partial assistant text")
            },
            open_tool_calls={},
            terminal_seen=False,
        ),
    )


def _make_completed_turn() -> CodexTurnSummary:
    return CodexTurnSummary(
        turn_id="turn_001",
        exchange_id="codex-exchange-001",
        session_id="ws_123",
        turn_index=0,
        request_message_index=0,
        terminal_message_index=2,
        terminal_cause="response_completed",
        message_range_start=0,
        message_range_end=2,
        model="codex/gpt-5-codex",
        status="completed",
        stop_reason="completed",
        text_chars=42,
        tool_calls=1,
        started_at=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 4, 19, 12, 0, 2, tzinfo=UTC),
        derivation_version=CODEX_DERIVATION_VERSION,
        cursor=CodexDerivationCursor(
            next_message_index=3,
            next_seq=4,
            open_assistant_items={},
            open_tool_calls={},
            terminal_seen=True,
        ),
    )


class TestAppendAndReadIndex:
    async def test_append_and_read(self, storage: DiskStorageBackend) -> None:
        entry = _make_index_entry()
        await storage.append_index(entry)
        entries = await storage.read_index(limit=10, offset=0)
        assert len(entries) == 1
        assert entries[0].id == "ex-001"

    async def test_read_empty(self, storage: DiskStorageBackend) -> None:
        entries = await storage.read_index(limit=10, offset=0)
        assert entries == []

    async def test_pagination(self, storage: DiskStorageBackend) -> None:
        for i in range(5):
            await storage.append_index(_make_index_entry(f"ex-{i:03d}"))
        page = await storage.read_index(limit=2, offset=1)
        assert len(page) == 2
        assert page[0].id == "ex-001"
        assert page[1].id == "ex-002"

    async def test_upsert_replaces_existing_row(
        self, storage: DiskStorageBackend
    ) -> None:
        original = _make_index_entry("ex-upsert")
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
        entry = _make_index_entry("ex-001").model_copy(
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
        entry = _make_index_entry("ex-001").model_copy(update={"spawn_anchor": None})

        await storage.append_index(entry)

        entries = await storage.read_index(limit=10, offset=0)
        assert entries[0].spawn_anchor is None
        assert entries[0].model_dump(mode="json")["spawn_anchor"] is None

    def test_entry_defaults_to_root_track(self) -> None:
        entry = IndexEntry.model_validate(_make_index_entry("ex-001").model_dump())

        assert entry.track_id == entry.run_id
        assert entry.parent_track_id is None
        assert entry.track_display_name is None
        assert entry.track_role == "parent"
        assert entry.spawn_anchor is None

    def test_spawn_order_rejects_negative_values(self) -> None:
        payload = _make_index_entry("ex-001").model_dump()
        payload["spawn_anchor"] = {
            "track_spawn_exchange_id": "ex-parent",
            "track_spawn_tool_use_id": "toolu_child",
            "track_spawn_order": -1,
        }

        with pytest.raises(ValueError):
            IndexEntry.model_validate(payload)


class TestLegacyFlatAnchorCacheInvalidation:
    """``DiskStorageBackend.__init__`` drops the cache root on startup when any
    index row still uses the pre-ALP-2039 top-level flat anchor keys. This is
    the migration boundary: old wire shape is rejected by validation rather
    than rewritten in place."""

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


class TestWriteAndReadExchange:
    async def test_round_trip(self, storage: DiskStorageBackend) -> None:
        ir = _make_ir()
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        artifacts = ExchangeArtifacts(request_raw=raw, request_ir=ir)

        await storage.write_exchange("abcdef01-1234", artifacts)
        loaded = await storage.read_exchange("abcdef01-1234")

        assert loaded.request_raw == raw
        assert loaded.request_ir == ir
        assert loaded.request_curated_raw is None
        assert loaded.request_curated_ir is None
        assert loaded.request_audit is None
        assert loaded.response_raw is None
        assert loaded.transport is None

    async def test_with_response(self, storage: DiskStorageBackend) -> None:
        from manicure.ir import InternalResponse, UsageStats

        ir = _make_ir()
        raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}'
        resp_raw = b'{"id":"msg_01","model":"claude-sonnet-4-20250514","content":[]}'
        resp_ir = InternalResponse(
            id="msg_01",
            model="anthropic/claude-sonnet-4-20250514",
            provider="anthropic",
            stop_reason="end_turn",
            usage=UsageStats(input_tokens=10, output_tokens=20),
            content=[],
        )

        artifacts = ExchangeArtifacts(
            request_raw=raw,
            request_ir=ir,
            response_raw=resp_raw,
            response_ir=resp_ir,
        )
        await storage.write_exchange("bbccdd02-5678", artifacts)
        loaded = await storage.read_exchange("bbccdd02-5678")

        assert loaded.response_raw == resp_raw
        assert loaded.response_ir is not None
        assert loaded.response_ir.id == "msg_01"

    async def test_with_curated_request_audit_and_transport(
        self, storage: DiskStorageBackend
    ) -> None:
        ir = _make_ir()
        curated_raw = b'{"model":"claude-sonnet-4-20250514","max_tokens":256}'
        artifacts = ExchangeArtifacts(
            request_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}',
            request_ir=ir,
            request_curated_raw=curated_raw,
            request_curated_ir=ir.model_copy(
                update={
                    "messages": [
                        Message(role="user", content=[TextBlock(text="patched")]),
                    ]
                }
            ),
            request_audit=_make_audit(),
            transport={
                "provider": "codex",
                "protocol": "websocket",
                "upgrade": {
                    "scheme": "wss",
                    "host": "chatgpt.com",
                    "path": "/backend-api/codex/responses",
                    "request_headers": [
                        {"name": "authorization", "value": "Bearer super-secret"},
                        {"name": "x-test", "value": "1"},
                    ],
                    "response_status_code": 101,
                    "response_headers": [
                        {"name": "set-cookie", "value": "session=secret; Path=/"},
                        {"name": "x-upstream", "value": "chatgpt"},
                    ],
                },
                "close": {
                    "close_code": 1000,
                    "close_reason": "done",
                    "closed_by_client": False,
                    "initial_client_frame_captured": True,
                    "client_message_count": 1,
                    "server_message_count": 2,
                },
                "messages": [
                    {
                        "direction": "client",
                        "is_text": True,
                        "size_bytes": 24,
                        "dropped": False,
                        "event_type": "response.create",
                        "payload_text": '{"type":"response.create"}',
                        "payload_json": {"type": "response.create"},
                        "payload_base64": None,
                    }
                ],
            },
        )

        await storage.write_exchange("codex0001-5678", artifacts)
        loaded = await storage.read_exchange("codex0001-5678")

        assert loaded.request_curated_raw == curated_raw
        assert loaded.request_curated_ir is not None
        block = loaded.request_curated_ir.messages[0].content[0]
        assert isinstance(block, TextBlock)
        assert block.text == "patched"
        assert loaded.request_audit is not None
        assert loaded.request_audit.entries[0].target == "system:0"
        assert loaded.transport is not None
        assert loaded.transport.provider == "codex"
        assert loaded.transport.close is not None
        assert loaded.transport.close.close_code == 1000
        request_headers = {
            header.name: header.value
            for header in loaded.transport.upgrade.request_headers
        }
        response_headers = {
            header.name: header.value
            for header in loaded.transport.upgrade.response_headers
        }
        assert request_headers["authorization"] == "Bearer [redacted]"
        assert request_headers["x-test"] == "1"
        assert response_headers["set-cookie"] == "[redacted]"
        assert response_headers["x-upstream"] == "chatgpt"
        assert loaded.transport.messages[0].event_type == "response.create"

    async def test_rewrite_existing_exchange_dir(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "rewrite01-1234"
        original_ir = _make_ir()
        await storage.write_exchange(
            exchange_id,
            ExchangeArtifacts(
                request_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}',
                request_ir=original_ir,
            ),
        )
        original_dir = storage._find_exchange_dir(exchange_id)

        final_response = InternalResponse(
            id="msg_final",
            model="anthropic/claude-sonnet-4-20250514",
            provider="anthropic",
            stop_reason="end_turn",
            usage=UsageStats(input_tokens=10, output_tokens=20),
            content=[TextBlock(text="done")],
        )
        await storage.write_exchange(
            exchange_id,
            ExchangeArtifacts(
                request_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}',
                request_ir=original_ir,
                request_curated_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":256}',
                request_curated_ir=original_ir.model_copy(
                    update={
                        "messages": [
                            Message(role="user", content=[TextBlock(text="patched")])
                        ]
                    }
                ),
                response_raw=b'{"id":"msg_final"}',
                response_ir=final_response,
            ),
        )

        dirs = [path for path in storage.root.iterdir() if path.is_dir()]
        assert dirs == [original_dir]
        loaded = await storage.read_exchange(exchange_id)
        assert loaded.request_curated_raw is not None
        assert loaded.response_ir is not None
        assert loaded.response_ir.id == "msg_final"

    async def test_read_exchange_redacts_and_rewrites_legacy_transport_headers(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "legacy000-5678"
        exchange_dir = storage.root / f"20250601T120000Z-{exchange_id[:8]}"
        exchange_dir.mkdir()
        (exchange_dir / "request.raw").write_bytes(
            b'{"type":"response.create","model":"gpt-5-codex"}'
        )
        (exchange_dir / "request.ir.json").write_text(_make_ir().model_dump_json())
        (exchange_dir / "transport.json").write_text(
            """
{
  "provider": "codex",
  "protocol": "websocket",
  "upgrade": {
    "scheme": "wss",
    "host": "chatgpt.com",
    "path": "/backend-api/codex/responses",
    "request_headers": [
      {"name": "authorization", "value": "Bearer legacy-secret"},
      {"name": "origin", "value": "https://chatgpt.com"}
    ],
    "response_status_code": 403,
    "response_headers": [
      {"name": "set-cookie", "value": "session=legacy; Path=/"},
      {"name": "content-type", "value": "application/json"}
    ]
  },
  "close": null,
  "messages": []
}
""".strip()
        )

        loaded = await storage.read_exchange(exchange_id)

        assert loaded.transport is not None
        request_headers = {
            header.name: header.value
            for header in loaded.transport.upgrade.request_headers
        }
        response_headers = {
            header.name: header.value
            for header in loaded.transport.upgrade.response_headers
        }
        assert request_headers["authorization"] == "Bearer [redacted]"
        assert request_headers["origin"] == "https://chatgpt.com"
        assert response_headers["set-cookie"] == "[redacted]"
        assert response_headers["content-type"] == "application/json"

        persisted = (exchange_dir / "transport.json").read_text()
        assert "legacy-secret" not in persisted
        assert "session=legacy" not in persisted
        assert "Bearer [redacted]" in persisted

    async def test_not_found(self, storage: DiskStorageBackend) -> None:
        with pytest.raises(FileNotFoundError):
            await storage.read_exchange("nonexistent-id")


class TestReadIndexEntry:
    async def test_returns_none_when_empty(self, storage: DiskStorageBackend) -> None:
        result = await storage.read_index_entry("nonexistent")
        assert result is None

    async def test_returns_correct_entry(self, storage: DiskStorageBackend) -> None:
        entry_a = _make_index_entry("aaaa1111")
        entry_b = _make_index_entry("bbbb2222")
        await storage.append_index(entry_a)
        await storage.append_index(entry_b)

        found = await storage.read_index_entry("aaaa1111")
        assert found is not None
        assert found.id == "aaaa1111"

        found_b = await storage.read_index_entry("bbbb2222")
        assert found_b is not None
        assert found_b.id == "bbbb2222"

    async def test_consistent_with_read_index(
        self, storage: DiskStorageBackend
    ) -> None:
        ids = [f"id{i:04d}" for i in range(5)]
        for eid in ids:
            await storage.append_index(_make_index_entry(eid))

        all_entries = await storage.read_index(limit=100, offset=0)
        assert len(all_entries) == 5

        for eid in ids:
            found = await storage.read_index_entry(eid)
            assert found is not None
            assert found.id == eid

    async def test_cache_updated_after_append(
        self, storage: DiskStorageBackend
    ) -> None:
        """Cache should reflect entries added after first read."""
        assert await storage.read_index_entry("cached-id") is None
        await storage.append_index(_make_index_entry("cached-id"))
        found = await storage.read_index_entry("cached-id")
        assert found is not None
        assert found.id == "cached-id"


class TestDeleteExchange:
    async def test_removes_index_row_and_artifacts(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "deadbeef-1234"
        await storage.append_index(_make_index_entry(exchange_id))
        await storage.write_exchange(
            exchange_id,
            ExchangeArtifacts(request_raw=b"{}", request_ir=_make_ir()),
        )

        removed = await storage.delete_exchange(exchange_id)

        assert removed is True
        assert await storage.read_index_entry(exchange_id) is None
        with pytest.raises(FileNotFoundError):
            await storage.read_exchange(exchange_id)

    async def test_returns_false_when_exchange_is_missing(
        self, storage: DiskStorageBackend
    ) -> None:
        assert await storage.delete_exchange("missing-0000") is False

    async def test_rewrite_failure_restores_index_row_and_artifacts(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "deadbeef-rollback"
        entry = _make_index_entry(exchange_id)
        artifacts = ExchangeArtifacts(request_raw=b"{}", request_ir=_make_ir())
        await storage.append_index(entry)
        await storage.write_exchange(exchange_id, artifacts)

        async def fail_rewrite(_: dict[str, IndexEntry]) -> None:
            raise OSError("index rewrite failed")

        with (
            patch.object(storage, "_rewrite_index", side_effect=fail_rewrite),
            pytest.raises(OSError, match="index rewrite failed"),
        ):
            await storage.delete_exchange(exchange_id)

        restored = await storage.read_index_entry(exchange_id)
        assert restored == entry
        restored_artifacts = await storage.read_exchange(exchange_id)
        assert restored_artifacts.request_raw == artifacts.request_raw

    async def test_rewrite_failure_preserves_cache_order(
        self, storage: DiskStorageBackend
    ) -> None:
        first = _make_index_entry("deadbeef-first")
        middle = _make_index_entry("deadbeef-middle")
        last = _make_index_entry("deadbeef-last")
        await storage.append_index(first)
        await storage.append_index(middle)
        await storage.append_index(last)

        async def fail_rewrite(_: dict[str, IndexEntry]) -> None:
            raise OSError("index rewrite failed")

        with (
            patch.object(storage, "_rewrite_index", side_effect=fail_rewrite),
            pytest.raises(OSError, match="index rewrite failed"),
        ):
            await storage.delete_exchange(middle.id)

        assert [entry.id for entry in await storage.read_index(limit=10, offset=0)] == [
            first.id,
            middle.id,
            last.id,
        ]
