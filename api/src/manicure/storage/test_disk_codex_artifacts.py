from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from manicure.codex.derivation import CODEX_DERIVATION_VERSION
from manicure.storage import test_disk as disk_tests
from manicure.storage.base import ExchangeArtifacts
from manicure.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from pathlib import Path

    from manicure.codex.events import CodexSemanticEvent, CodexTurnSummary
    from manicure.storage.base import TransportArtifacts


@pytest.fixture
def storage(tmp_path: str) -> DiskStorageBackend:
    return DiskStorageBackend(root=str(tmp_path))


def _codex_transport() -> dict[str, object]:
    return {
        "provider": "codex",
        "protocol": "websocket",
        "upgrade": {
            "scheme": "wss",
            "host": "chatgpt.com",
            "path": "/backend-api/codex/responses",
            "request_headers": [],
            "response_status_code": 101,
            "response_headers": [],
        },
        "close": None,
        "messages": [],
    }


class TestCodexDerivedArtifacts:
    async def test_with_codex_derived_artifacts(
        self, storage: DiskStorageBackend
    ) -> None:
        event = disk_tests._make_codex_event()
        turn = disk_tests._make_open_turn()
        artifacts = ExchangeArtifacts(
            request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
            request_ir=disk_tests._make_ir(),
            transport=_codex_transport(),
            events=(event,),
            turn=turn,
        )

        await storage.write_exchange("codexturn-1234", artifacts)
        loaded = await storage.read_exchange("codexturn-1234")

        assert loaded.events == (event,)
        assert loaded.turn == turn
        assert loaded.turn is not None
        assert loaded.turn.cursor is not None
        assert loaded.turn.derivation_version == CODEX_DERIVATION_VERSION

    async def test_finalized_turn_strips_cursor_when_persisted(
        self, storage: DiskStorageBackend
    ) -> None:
        await storage.write_exchange(
            "codexdone-1234",
            ExchangeArtifacts(
                request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
                request_ir=disk_tests._make_ir(),
                events=(disk_tests._make_codex_event(),),
                turn=disk_tests._make_completed_turn(),
            ),
        )

        loaded = await storage.read_exchange("codexdone-1234")

        assert loaded.turn is not None
        assert loaded.turn.status == "completed"
        assert loaded.turn.cursor is None

    async def test_transport_is_written_before_events_and_turn(
        self, storage: DiskStorageBackend
    ) -> None:
        calls: list[str] = []
        original_transport = storage._write_transport_json
        original_events = storage._write_events_jsonl
        original_turn = storage._write_turn_json

        async def write_transport(path: Path, transport: TransportArtifacts) -> None:
            calls.append("transport")
            await original_transport(path, transport)

        async def write_events(
            path: Path, events: tuple[CodexSemanticEvent, ...]
        ) -> None:
            calls.append("events")
            await original_events(path, events)

        async def write_turn(path: Path, turn: CodexTurnSummary) -> None:
            calls.append("turn")
            await original_turn(path, turn)

        with (
            patch.object(storage, "_write_transport_json", side_effect=write_transport),
            patch.object(storage, "_write_events_jsonl", side_effect=write_events),
            patch.object(storage, "_write_turn_json", side_effect=write_turn),
        ):
            await storage.write_exchange(
                "codexorder-1234",
                ExchangeArtifacts(
                    request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
                    request_ir=disk_tests._make_ir(),
                    transport=_codex_transport(),
                    events=(disk_tests._make_codex_event(),),
                    turn=disk_tests._make_open_turn(),
                ),
            )

        assert calls == ["transport", "events", "turn"]

    async def test_write_codex_derived_artifacts_restores_original_sidecars_on_failure(
        self, storage: DiskStorageBackend
    ) -> None:
        exchange_id = "codexrepair-5678"
        original_event = disk_tests._make_codex_event().model_copy(
            update={"exchange_id": exchange_id}
        )
        original_turn = disk_tests._make_open_turn().model_copy(
            update={"exchange_id": exchange_id}
        )
        original_artifacts = ExchangeArtifacts(
            request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
            request_ir=disk_tests._make_ir(),
            transport=_codex_transport(),
            events=(original_event,),
            turn=original_turn,
        )
        await storage.write_exchange(exchange_id, original_artifacts)

        exchange_dir = storage._find_exchange_dir(exchange_id)
        original_events_bytes = (exchange_dir / "events.jsonl").read_bytes()
        original_turn_bytes = (exchange_dir / "turn.json").read_bytes()

        updated_event = original_event.model_copy(update={"data": {"repaired": True}})
        updated_turn = original_turn.model_copy(update={"text_chars": 64})

        async def fail_turn(*_: object) -> None:
            raise OSError("turn write failed")

        with (
            patch.object(storage, "_write_turn_json", side_effect=fail_turn),
            pytest.raises(OSError, match="turn write failed"),
        ):
            await storage.write_codex_derived_artifacts(
                exchange_id,
                original_artifacts.model_copy(
                    update={"events": (updated_event,), "turn": updated_turn}
                ),
            )

        restored_dir = storage._find_exchange_dir(exchange_id)
        assert restored_dir == exchange_dir
        assert (restored_dir / "events.jsonl").read_bytes() == original_events_bytes
        assert (restored_dir / "turn.json").read_bytes() == original_turn_bytes

        loaded = await storage.read_exchange(exchange_id)
        assert loaded.events == (original_event,)
        assert loaded.turn == original_turn
        assert not any(
            path.name.endswith((".tmp", ".bak")) for path in storage.root.iterdir()
        )

    async def test_write_exchange_rejects_incomplete_derived_artifacts(
        self, storage: DiskStorageBackend
    ) -> None:
        with pytest.raises(
            ValueError,
            match="Codex derived artifacts require both events and turn",
        ):
            await storage.write_exchange(
                "codexinvalid-1234",
                ExchangeArtifacts(
                    request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
                    request_ir=disk_tests._make_ir(),
                    turn=disk_tests._make_open_turn(),
                ),
            )

        with pytest.raises(FileNotFoundError):
            await storage.read_exchange("codexinvalid-1234")
        assert not any(path.name.endswith(".tmp") for path in storage.root.iterdir())

    async def test_persist_exchange_rejects_mismatched_derived_artifacts(
        self, storage: DiskStorageBackend
    ) -> None:
        mismatched_turn = disk_tests._make_open_turn().model_copy(
            update={"exchange_id": "codex-exchange-999"}
        )
        entry = disk_tests._make_index_entry("codexinvalid-5678")

        with pytest.raises(
            ValueError, match="event exchange_id must match turn.exchange_id"
        ):
            await storage.persist_exchange(
                entry,
                ExchangeArtifacts(
                    request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
                    request_ir=disk_tests._make_ir(),
                    transport=_codex_transport(),
                    events=(disk_tests._make_codex_event(),),
                    turn=mismatched_turn,
                ),
            )

        assert await storage.read_index(limit=10, offset=0) == []
        with pytest.raises(FileNotFoundError):
            await storage.read_exchange(entry.id)
        assert not any(
            path.name.endswith((".tmp", ".bak")) for path in storage.root.iterdir()
        )
