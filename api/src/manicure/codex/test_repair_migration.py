from __future__ import annotations

import json
from typing import TYPE_CHECKING

from manicure.codex.repair import repair_codex_derived_artifacts
from manicure.storage.base import ExchangeArtifacts

from .test_repair_support import (
    _codex_ir,
    _codex_transport,
    _message,
    _ts,
    _write_sidecar,
)

pytest_plugins = ("manicure.codex.test_repair_support",)

if TYPE_CHECKING:
    from manicure.storage.disk import DiskStorageBackend


async def test_repair_migrates_unsupported_codex_sidecars_and_preserves_turn_identity(
    storage: DiskStorageBackend,
) -> None:
    exchange_id = "codexmigr8-1234"
    request_ir = _codex_ir()
    artifacts = ExchangeArtifacts(
        request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
        request_ir=request_ir,
        transport=_codex_transport(
            _message(
                direction="client",
                second=0,
                payload={"type": "response.create", "model": "gpt-5-codex"},
            ),
            _message(
                direction="server",
                second=2,
                payload={
                    "type": "response.completed",
                    "response": {"status": "completed"},
                },
            ),
        ),
    )

    await storage.write_exchange(exchange_id, artifacts)
    exchange_dir = storage._find_exchange_dir(exchange_id)
    legacy_turn = {
        "turn_id": "legacy-turn",
        "exchange_id": exchange_id,
        "session_id": "ws_123",
        "turn_index": 7,
        "request_message_index": 0,
        "terminal_message_index": 1,
        "terminal_cause": "response_completed",
        "message_range_start": 0,
        "message_range_end": 1,
        "model": "codex/gpt-5-codex",
        "status": "completed",
        "stop_reason": "completed",
        "text_chars": 0,
        "tool_calls": 0,
        "started_at": _ts(0).isoformat(),
        "ended_at": _ts(2).isoformat(),
        "derivation_version": 2,
    }
    legacy_events = [
        {
            "event_id": "evt_000001",
            "exchange_id": exchange_id,
            "session_id": "ws_123",
            "turn_id": "legacy-turn",
            "seq": 1,
            "ts": _ts(0).isoformat(),
            "source": "proxy",
            "kind": "request_curated",
            "data": {"source": "legacy"},
            "derivation_version": 2,
        },
        {
            "event_id": "evt_000002",
            "exchange_id": exchange_id,
            "session_id": "ws_123",
            "turn_id": "legacy-turn",
            "seq": 2,
            "ts": _ts(1).isoformat(),
            "source": "operator",
            "kind": "breakpoint_paused",
            "data": {"flow_id": "flow-1"},
            "derivation_version": 2,
        },
        {
            "event_id": "evt_000003",
            "exchange_id": exchange_id,
            "session_id": "ws_123",
            "turn_id": "legacy-turn",
            "seq": 3,
            "ts": _ts(2).isoformat(),
            "source": "operator",
            "kind": "breakpoint_released",
            "data": {"flow_id": "flow-1"},
            "derivation_version": 2,
        },
    ]
    _write_sidecar(exchange_dir / "turn.json", json.dumps(legacy_turn).encode())
    _write_sidecar(
        exchange_dir / "events.jsonl",
        "".join(json.dumps(event) + "\n" for event in legacy_events).encode(),
    )

    result = await repair_codex_derived_artifacts(storage, exchange_id)

    assert result.action == "migrated"
    assert result.status_before == "migration_required"

    loaded = await storage.read_exchange(exchange_id)
    assert loaded.turn is not None
    assert loaded.turn.turn_id == "legacy-turn"
    assert loaded.turn.turn_index == 7
    assert loaded.events is not None
    operator_events = [
        event
        for event in loaded.events
        if event.kind in {"request_curated", "breakpoint_paused", "breakpoint_released"}
    ]
    assert [event.kind for event in operator_events] == [
        "request_curated",
        "breakpoint_paused",
        "breakpoint_released",
    ]
    assert [event.ts for event in operator_events] == [_ts(0), _ts(1), _ts(2)]
