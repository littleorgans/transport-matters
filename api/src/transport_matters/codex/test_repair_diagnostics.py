from __future__ import annotations

import json
from typing import TYPE_CHECKING

from transport_matters.codex.repair import (
    repair_codex_derived_artifacts,
    resolve_codex_derived_artifacts,
)
from transport_matters.storage.base import ExchangeArtifacts

from .test_repair_support import (
    _codex_ir,
    _codex_transport,
    _message,
    _ts,
    _write_sidecar,
)

pytest_plugins = ("transport_matters.codex.test_repair_support",)

if TYPE_CHECKING:
    from transport_matters.storage.disk import DiskStorageBackend


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
