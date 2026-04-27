from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from manicure.codex.repair import repair_codex_derived_artifacts
from manicure.overrides import OverrideAudit, OverrideAuditEntry
from manicure.storage.base import ExchangeArtifacts

from .test_repair_support import (
    _close,
    _codex_ir,
    _codex_transport,
    _message,
)

pytest_plugins = ("manicure.codex.test_repair_support",)

if TYPE_CHECKING:
    from manicure.storage.disk import DiskStorageBackend


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
