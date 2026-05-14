from __future__ import annotations

from typing import TYPE_CHECKING

from transport_matters.codex import CodexAdapter
from transport_matters.codex.repair import repair_codex_derived_artifacts
from transport_matters.ir import Message, RequestMetadata, TextBlock
from transport_matters.storage.base import ExchangeArtifacts

from .test_repair_support import (
    _codex_ir,
    _codex_transport,
    _live_codex_derivation,
    _message,
    _payload_json,
)

pytest_plugins = ("transport_matters.codex.test_repair_support",)

if TYPE_CHECKING:
    from transport_matters.storage.disk import DiskStorageBackend


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
                "name": "session-id",
                "value": "ws_from_header",
            },
            {
                "name": "thread-id",
                "value": "thread_from_header",
            },
            {
                "name": "x-codex-turn-metadata",
                "value": _payload_json({"turn_id": "turn_from_header"}),
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
