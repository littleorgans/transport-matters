from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from manicure.codex import CodexAdapter
from manicure.codex.exchange_derivation import _replay_codex_derived_artifacts
from manicure.codex.repair import (
    repair_codex_derived_artifacts,
    resolve_codex_derived_artifacts,
)
from manicure.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from manicure.overrides import OverrideAudit, OverrideAuditEntry
from manicure.storage.base import ExchangeArtifacts
from manicure.storage.disk import DiskStorageBackend

if TYPE_CHECKING:
    from pathlib import Path

    from mitmproxy import http

    from manicure.codex.derivation import CodexDerivedTurnArtifacts
    from manicure.storage.base import TransportArtifacts


@pytest.fixture
def storage(tmp_path: str) -> DiskStorageBackend:
    return DiskStorageBackend(root=str(tmp_path))


def _ts(second: int) -> datetime:
    return datetime(2026, 4, 19, 12, 0, second, tzinfo=UTC)


def _payload_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, separators=(",", ":"))


def _message(
    *,
    direction: str,
    second: int | None,
    payload: dict[str, object],
    dropped: bool = False,
) -> dict[str, object]:
    payload_text = _payload_json(payload)
    return {
        "ts": None if second is None else _ts(second),
        "direction": direction,
        "is_text": True,
        "size_bytes": len(payload_text.encode()),
        "dropped": dropped,
        "event_type": payload.get("type"),
        "payload_text": payload_text,
        "payload_json": payload,
        "payload_base64": None,
    }


def _codex_transport(
    *messages: dict[str, object],
    close: dict[str, object] | None = None,
    request_headers: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "provider": "codex",
        "protocol": "websocket",
        "upgrade": {
            "scheme": "wss",
            "host": "chatgpt.com",
            "path": "/backend-api/codex/responses",
            "request_headers": request_headers or [],
            "response_status_code": 101,
            "response_headers": [],
        },
        "close": close,
        "messages": list(messages),
    }


def _close(
    *,
    second: int | None,
    close_code: int | None = 1000,
    close_reason: str | None = "done",
    client_message_count: int = 1,
    server_message_count: int = 0,
) -> dict[str, object]:
    return {
        "ts": None if second is None else _ts(second),
        "close_code": close_code,
        "close_reason": close_reason,
        "closed_by_client": False,
        "initial_client_frame_captured": True,
        "client_message_count": client_message_count,
        "server_message_count": server_message_count,
    }


def _codex_ir(session_id: str = "ws_123") -> InternalRequest:
    return InternalRequest(
        model="codex/gpt-5-codex",
        provider="codex",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hi")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(
            session_id=session_id,
            provider_metadata={"session_id": session_id},
        ),
    )


def _write_sidecar(path: Path, payload: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(payload)


def _live_codex_derivation(
    *,
    exchange_id: str,
    request_ir: InternalRequest,
    transport: TransportArtifacts,
    audit: OverrideAudit | None = None,
    mutated_manually: bool = False,
) -> CodexDerivedTurnArtifacts:
    derived = _replay_codex_derived_artifacts(
        cast(
            "http.HTTPFlow",
            SimpleNamespace(
                metadata={},
                request=SimpleNamespace(headers={}),
            ),
        ),
        exchange_id=exchange_id,
        request_state=SimpleNamespace(
            request_ir=request_ir,
            audit=audit,
            mutated_manually=mutated_manually,
        ),
        transport=transport,
        turn_index=0,
    )
    assert derived is not None
    return derived


async def test_repair_rebuilds_missing_codex_sidecars_without_rewriting_transport(
    storage: DiskStorageBackend,
) -> None:
    exchange_id = "codexrepair-1234"
    request_ir = _codex_ir()
    transport = _codex_transport(
        _message(
            direction="client",
            second=0,
            payload={"type": "response.create", "model": "gpt-5-codex"},
        ),
        _message(
            direction="server",
            second=1,
            payload={
                "type": "response.output_item.done",
                "item": {
                    "id": "msg_01",
                    "type": "message",
                    "status": "completed",
                    "phase": "final_answer",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "hello"}],
                },
            },
        ),
        _message(
            direction="server",
            second=2,
            payload={"type": "response.completed", "response": {"status": "completed"}},
        ),
    )
    artifacts = ExchangeArtifacts(
        request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
        request_ir=request_ir,
        request_curated_ir=request_ir.model_copy(
            update={
                "messages": [Message(role="user", content=[TextBlock(text="edited")])]
            }
        ),
        transport=transport,
    )

    await storage.write_exchange(exchange_id, artifacts)
    exchange_dir = storage._find_exchange_dir(exchange_id)
    transport_before = (exchange_dir / "transport.json").read_bytes()

    result = await repair_codex_derived_artifacts(storage, exchange_id)

    assert result.action == "repaired"
    assert result.status_before == "missing"
    assert (exchange_dir / "transport.json").read_bytes() == transport_before

    loaded = await storage.read_exchange(exchange_id)
    assert loaded.events is not None
    assert loaded.turn is not None
    assert loaded.transport is not None
    live = _live_codex_derivation(
        exchange_id=exchange_id,
        request_ir=request_ir,
        transport=loaded.transport,
        mutated_manually=True,
    )
    assert [event.model_dump(mode="json") for event in loaded.events] == [
        event.model_dump(mode="json") for event in live.events
    ]
    assert loaded.turn.model_dump(mode="json") == live.turn.model_dump(mode="json")
    assert [event.kind for event in loaded.events] == [
        "turn_started",
        "request_curated",
        "assistant_item_completed",
        "response_completed",
        "turn_finalized",
    ]
    assert loaded.turn.status == "completed"
    assert loaded.turn.request_message_index == 0
    assert loaded.turn.terminal_message_index == 2


async def test_repair_matches_live_timeline_for_unedited_codex_turn_with_raw_only_snapshot(
    storage: DiskStorageBackend,
) -> None:
    exchange_id = "codexrepairraw-1234"
    request_ir = _codex_ir()
    transport = _codex_transport(
        _message(
            direction="client",
            second=0,
            payload={"type": "response.create", "model": "gpt-5-codex"},
        ),
        _message(
            direction="server",
            second=1,
            payload={
                "type": "response.output_item.done",
                "item": {
                    "id": "msg_01",
                    "type": "message",
                    "status": "completed",
                    "phase": "final_answer",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "hello"}],
                },
            },
        ),
        _message(
            direction="server",
            second=2,
            payload={"type": "response.completed", "response": {"status": "completed"}},
        ),
    )
    artifacts = ExchangeArtifacts(
        request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
        request_ir=request_ir,
        request_curated_raw=CodexAdapter().outbound_request(request_ir),
        transport=transport,
    )

    await storage.write_exchange(exchange_id, artifacts)

    result = await repair_codex_derived_artifacts(storage, exchange_id)

    assert result.action == "repaired"
    assert result.status_before == "missing"

    loaded = await storage.read_exchange(exchange_id)
    assert loaded.events is not None
    assert loaded.turn is not None
    assert loaded.transport is not None
    live = _live_codex_derivation(
        exchange_id=exchange_id,
        request_ir=request_ir,
        transport=loaded.transport,
    )
    assert [event.model_dump(mode="json") for event in loaded.events] == [
        event.model_dump(mode="json") for event in live.events
    ]
    assert loaded.turn.model_dump(mode="json") == live.turn.model_dump(mode="json")
    assert [event.kind for event in loaded.events] == [
        "turn_started",
        "assistant_item_completed",
        "response_completed",
        "turn_finalized",
    ]


async def test_repair_does_not_invent_request_curated_from_audit_only(
    storage: DiskStorageBackend,
) -> None:
    exchange_id = "codexrepairaudit-1234"
    request_ir = _codex_ir()
    transport = _codex_transport(
        _message(
            direction="client",
            second=0,
            payload={"type": "response.create", "model": "gpt-5-codex"},
        ),
        _message(
            direction="server",
            second=1,
            payload={
                "type": "response.output_item.done",
                "item": {
                    "id": "msg_01",
                    "type": "message",
                    "status": "completed",
                    "phase": "final_answer",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": "hello"}],
                },
            },
        ),
        _message(
            direction="server",
            second=2,
            payload={"type": "response.completed", "response": {"status": "completed"}},
        ),
    )
    artifacts = ExchangeArtifacts(
        request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
        request_ir=request_ir,
        request_audit=OverrideAudit(
            entries=[
                OverrideAuditEntry(
                    kind="truncate_tool_result",
                    target="toolresult:tu-1",
                    applied=True,
                    chars_delta=0,
                    curated_value="tiny",
                )
            ],
            chars_before=4,
            chars_after=4,
        ),
        transport=transport,
    )

    await storage.write_exchange(exchange_id, artifacts)

    result = await repair_codex_derived_artifacts(storage, exchange_id)

    assert result.action == "repaired"
    assert result.status_before == "missing"

    loaded = await storage.read_exchange(exchange_id)
    assert loaded.events is not None
    assert [event.kind for event in loaded.events] == [
        "turn_started",
        "assistant_item_completed",
        "response_completed",
        "turn_finalized",
    ]


async def test_repair_rebuilds_missing_codex_sidecars_from_transport_turn_metadata(
    storage: DiskStorageBackend,
) -> None:
    exchange_id = "codexrepairhdr-1234"
    request_ir = _codex_ir().model_copy(
        update={"metadata": RequestMetadata(provider_metadata={})}
    )
    transport = _codex_transport(
        _message(
            direction="client",
            second=0,
            payload={"type": "response.create", "model": "gpt-5-codex"},
        ),
        _message(
            direction="server",
            second=1,
            payload={
                "type": "response.completed",
                "response": {"status": "completed"},
            },
        ),
        request_headers=[
            {
                "name": "x-codex-session",
                "value": "[redacted]",
            },
            {
                "name": "x-codex-turn-metadata",
                "value": _payload_json({"session_id": "ws_from_header"}),
            },
        ],
    )
    artifacts = ExchangeArtifacts(
        request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
        request_ir=request_ir,
        transport=transport,
    )

    await storage.write_exchange(exchange_id, artifacts)

    result = await repair_codex_derived_artifacts(storage, exchange_id)

    assert result.action == "repaired"
    loaded = await storage.read_exchange(exchange_id)
    assert loaded.turn is not None
    assert loaded.turn.session_id == "ws_from_header"


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


async def test_resolve_reports_incomplete_codex_sidecars(
    storage: DiskStorageBackend,
) -> None:
    exchange_id = "codexbad-1234"
    artifacts = ExchangeArtifacts(
        request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
        request_ir=_codex_ir(),
        transport=_codex_transport(
            _message(
                direction="client",
                second=0,
                payload={"type": "response.create", "model": "gpt-5-codex"},
            ),
            _message(
                direction="server",
                second=1,
                payload={
                    "type": "response.completed",
                    "response": {"status": "completed"},
                },
            ),
        ),
    )

    await storage.write_exchange(exchange_id, artifacts)
    exchange_dir = storage._find_exchange_dir(exchange_id)
    _write_sidecar(
        exchange_dir / "events.jsonl",
        (
            json.dumps(
                {
                    "event_id": "evt_000001",
                    "exchange_id": exchange_id,
                    "session_id": "ws_123",
                    "turn_id": exchange_id,
                    "seq": 1,
                    "ts": _ts(0).isoformat(),
                    "source": "client",
                    "kind": "turn_started",
                    "transport_ref": {"message_index": 0},
                    "data": {},
                    "derivation_version": 1,
                }
            )
            + "\n"
        ).encode(),
    )

    loaded = await storage.read_exchange(exchange_id)
    files = await storage.read_codex_derived_files(exchange_id)
    resolution = resolve_codex_derived_artifacts(loaded, files)

    assert resolution.status == "inconsistent"
    assert {diagnostic.code for diagnostic in resolution.diagnostics} >= {
        "codex_derived_incomplete"
    }


async def test_repair_reports_missing_transport_message_timestamps(
    storage: DiskStorageBackend,
) -> None:
    exchange_id = "codextsless-1234"
    artifacts = ExchangeArtifacts(
        request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
        request_ir=_codex_ir(),
        transport=_codex_transport(
            _message(
                direction="client",
                second=None,
                payload={"type": "response.create", "model": "gpt-5-codex"},
            ),
            _message(
                direction="server",
                second=None,
                payload={
                    "type": "response.completed",
                    "response": {"status": "completed"},
                },
            ),
        ),
    )

    await storage.write_exchange(exchange_id, artifacts)

    result = await repair_codex_derived_artifacts(storage, exchange_id)

    assert result.action == "none"
    assert result.status_before == "missing"
    assert {diagnostic.code for diagnostic in result.diagnostics} >= {
        "codex_transport_message_timestamp_missing"
    }


@pytest.mark.parametrize(
    ("exchange_id", "transport"),
    [
        (
            "codexhandshake-4321",
            _codex_transport(
                _message(
                    direction="server",
                    second=0,
                    payload={
                        "type": "response.failed",
                        "response": {"status": "failed"},
                    },
                )
            ),
        ),
        (
            "codexdropped-4321",
            _codex_transport(
                _message(
                    direction="client",
                    second=0,
                    payload={"type": "response.create", "model": "gpt-5-codex"},
                    dropped=True,
                ),
                close=_close(second=1, close_code=1000),
            ),
        ),
    ],
)
async def test_repair_does_not_invent_sidecars_for_non_turn_transport(
    storage: DiskStorageBackend,
    exchange_id: str,
    transport: dict[str, object],
) -> None:
    await storage.write_exchange(
        exchange_id,
        ExchangeArtifacts(
            request_raw=b'{"type":"response.create","model":"gpt-5-codex"}',
            request_ir=_codex_ir(),
            transport=transport,
        ),
    )

    result = await repair_codex_derived_artifacts(storage, exchange_id)

    assert result.action == "none"
    assert result.status_before == "missing"
    assert {diagnostic.code for diagnostic in result.diagnostics} >= {
        "codex_turn_not_present"
    }

    exchange_dir = storage._find_exchange_dir(exchange_id)
    assert not (exchange_dir / "events.jsonl").exists()
    assert not (exchange_dir / "turn.json").exists()

    loaded = await storage.read_exchange(exchange_id)
    assert loaded.events is None
    assert loaded.turn is None
