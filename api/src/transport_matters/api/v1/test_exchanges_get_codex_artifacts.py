"""Codex derived artifact regressions for the exchange detail endpoint."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from transport_matters.codex.derivation import (
    CodexReplayRequest,
    derive_codex_turn_replay,
)
from transport_matters.codex.test_derivation_support import make_context, make_message
from transport_matters.ir import RequestMetadata
from transport_matters.storage.base import ExchangeArtifacts

from .test_exchanges_support import make_index_entry, make_ir

if TYPE_CHECKING:
    from httpx import AsyncClient

    from transport_matters.storage.disk import DiskStorageBackend


def _make_codex_replay_messages() -> tuple[Any, Any]:
    return (
        make_message(
            23,
            10,
            14,
            3,
            direction="client",
            event_type="response.create",
            payload_json={
                "type": "response.create",
                "model": "gpt-5-codex",
            },
        ),
        make_message(
            24,
            10,
            14,
            4,
            direction="server",
            event_type="response.completed",
            payload_json={
                "type": "response.completed",
                "response": {
                    "id": "resp_01",
                    "status": "completed",
                },
            },
        ),
    )


def _make_codex_transport_messages() -> list[Any]:
    request_fact, response_fact = _make_codex_replay_messages()
    request_payload = cast("dict[str, object]", request_fact.payload_json)
    response_payload = cast("dict[str, object]", response_fact.payload_json)
    return [
        {
            "ts": request_fact.ts,
            "direction": request_fact.direction,
            "is_text": True,
            "size_bytes": len(
                json.dumps(request_payload, separators=(",", ":")).encode()
            ),
            "dropped": request_fact.dropped,
            "event_type": request_fact.event_type,
            "payload_text": json.dumps(request_payload, separators=(",", ":")),
            "payload_json": request_payload,
            "payload_base64": None,
        },
        {
            "ts": response_fact.ts,
            "direction": response_fact.direction,
            "is_text": True,
            "size_bytes": len(
                json.dumps(response_payload, separators=(",", ":")).encode()
            ),
            "dropped": response_fact.dropped,
            "event_type": response_fact.event_type,
            "payload_text": json.dumps(response_payload, separators=(",", ":")),
            "payload_json": response_payload,
            "payload_base64": None,
        },
    ]


def _make_codex_transport() -> dict[str, Any]:
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
        "messages": _make_codex_transport_messages(),
    }


def _make_codex_derived_artifacts(
    *, exchange_id: str = "ex-001", turn_id: str = "turn-001"
) -> ExchangeArtifacts:
    ir = make_ir().model_copy(
        update={
            "provider": "codex",
            "model": "codex/gpt-5-codex",
            "metadata": RequestMetadata(
                session_id="ws-api",
                provider_metadata={"session_id": "ws-api"},
            ),
        }
    )
    transport = _make_codex_transport()
    derived = derive_codex_turn_replay(
        CodexReplayRequest(
            context=make_context(
                exchange_id=exchange_id,
                session_id="ws-api",
                turn_id=turn_id,
                turn_index=1,
                model="codex/gpt-5-codex",
            ),
            transport_messages=_make_codex_replay_messages(),
        )
    )
    assert derived is not None
    return ExchangeArtifacts(
        request_raw=b'{"type":"response.create"}',
        request_ir=ir,
        transport=transport,
        events=derived.events,
        turn=derived.turn,
    )


def _make_transport_only_codex_artifacts() -> ExchangeArtifacts:
    ir = make_ir().model_copy(
        update={
            "provider": "codex",
            "model": "codex/gpt-5-codex",
            "metadata": RequestMetadata(
                session_id="ws-api",
                provider_metadata={"session_id": "ws-api"},
            ),
        }
    )
    return ExchangeArtifacts(
        request_raw=b'{"type":"response.create"}',
        request_ir=ir,
        transport=_make_codex_transport(),
    )


def _diagnostic_codes(payload: dict[str, object]) -> set[str]:
    codex_derived_artifacts = cast(
        "dict[str, object] | None", payload.get("codex_derived_artifacts")
    )
    assert codex_derived_artifacts is not None
    diagnostics = cast("list[dict[str, Any]]", codex_derived_artifacts["diagnostics"])
    return {cast("str", diagnostic["code"]) for diagnostic in diagnostics}


async def test_get_existing_surfaces_supported_codex_sidecars(
    client: AsyncClient,
    monkeypatch: Any,
) -> None:
    import transport_matters.api.v1.exchanges as exchange_routes
    from transport_matters.storage import get_storage

    async def unexpected_repair(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("supported Codex exchanges should not repair on read")

    monkeypatch.setattr(
        exchange_routes, "repair_codex_derived_artifacts", unexpected_repair
    )

    storage = cast("DiskStorageBackend", await get_storage())
    entry = make_index_entry().model_copy(
        update={
            "provider": "codex",
            "model": "codex/gpt-5-codex",
        }
    )
    await storage.append_index(entry)
    await storage.write_exchange("ex-001", _make_codex_derived_artifacts())

    response = await client.get("/api/exchanges/ex-001")
    assert response.status_code == 200
    data = response.json()
    assert data["events"] is not None
    assert data["turn"] is not None
    assert data["codex_derived_artifacts"] == {
        "status": "supported",
        "diagnostics": [],
        "repair": None,
    }


async def test_get_existing_surfaces_incomplete_codex_sidecars(
    client: AsyncClient,
) -> None:
    from transport_matters.storage import get_storage

    storage = cast("DiskStorageBackend", await get_storage())
    entry = make_index_entry().model_copy(
        update={
            "provider": "codex",
            "model": "codex/gpt-5-codex",
        }
    )
    await storage.append_index(entry)
    await storage.write_exchange("ex-001", _make_codex_derived_artifacts())

    exchange_dir = storage._find_exchange_dir("ex-001")
    (exchange_dir / "turn.json").unlink()

    response = await client.get("/api/exchanges/ex-001")
    assert response.status_code == 200
    data = response.json()
    assert data["events"] is not None
    assert data["turn"] is not None
    assert data["codex_derived_artifacts"]["status"] == "supported"
    assert data["codex_derived_artifacts"]["repair"] == {
        "action": "repaired",
        "status_before": "inconsistent",
    }
    assert _diagnostic_codes(data) >= {"codex_derived_incomplete"}


async def test_get_existing_surfaces_unsupported_codex_sidecars(
    client: AsyncClient,
) -> None:
    from transport_matters.storage import get_storage

    storage = cast("DiskStorageBackend", await get_storage())
    entry = make_index_entry().model_copy(
        update={
            "provider": "codex",
            "model": "codex/gpt-5-codex",
        }
    )
    await storage.append_index(entry)
    await storage.write_exchange("ex-001", _make_codex_derived_artifacts())

    exchange_dir = storage._find_exchange_dir("ex-001")
    turn_payload = json.loads((exchange_dir / "turn.json").read_text())
    turn_payload["derivation_version"] = 99
    (exchange_dir / "turn.json").write_text(json.dumps(turn_payload))

    response = await client.get("/api/exchanges/ex-001")
    assert response.status_code == 200
    data = response.json()
    assert data["events"] is not None
    assert data["turn"] is not None
    assert data["codex_derived_artifacts"]["status"] == "supported"
    assert data["codex_derived_artifacts"]["repair"] == {
        "action": "migrated",
        "status_before": "migration_required",
    }
    assert _diagnostic_codes(data) >= {"codex_derived_migration_required"}


async def test_get_existing_surfaces_legacy_transport_only_codex_exchange(
    client: AsyncClient,
) -> None:
    from transport_matters.storage import get_storage

    storage = cast("DiskStorageBackend", await get_storage())
    entry = make_index_entry().model_copy(
        update={
            "provider": "codex",
            "model": "codex/gpt-5-codex",
        }
    )
    await storage.append_index(entry)
    await storage.write_exchange("ex-001", _make_transport_only_codex_artifacts())

    response = await client.get("/api/exchanges/ex-001")
    assert response.status_code == 200
    data = response.json()
    assert data["transport"]["provider"] == "codex"
    assert data["events"] is not None
    assert data["turn"] is not None
    assert data["codex_derived_artifacts"]["status"] == "supported"
    assert data["codex_derived_artifacts"]["repair"] == {
        "action": "repaired",
        "status_before": "missing",
    }
    assert _diagnostic_codes(data) >= {"codex_derived_missing"}


async def test_get_existing_surfaces_irreparable_codex_sidecars(
    client: AsyncClient,
) -> None:
    from transport_matters.storage import get_storage

    storage = cast("DiskStorageBackend", await get_storage())
    entry = make_index_entry().model_copy(
        update={
            "provider": "codex",
            "model": "codex/gpt-5-codex",
        }
    )
    await storage.append_index(entry)

    artifacts = _make_transport_only_codex_artifacts()
    assert artifacts.transport is not None
    transport_messages = [
        message.model_copy(update={"ts": None})
        for message in artifacts.transport.messages
    ]
    await storage.write_exchange(
        "ex-001",
        artifacts.model_copy(
            update={
                "transport": artifacts.transport.model_copy(
                    update={"messages": transport_messages}
                )
            }
        ),
    )

    response = await client.get("/api/exchanges/ex-001")
    assert response.status_code == 200
    data = response.json()
    assert data["events"] is None
    assert data["turn"] is None
    assert data["codex_derived_artifacts"]["status"] == "missing"
    assert data["codex_derived_artifacts"]["repair"] == {
        "action": "none",
        "status_before": "missing",
    }
    assert _diagnostic_codes(data) >= {
        "codex_derived_missing",
        "codex_transport_message_timestamp_missing",
    }
