"""HARD REQ #1 regression guard: the codex wire-capture finalize seam MUST feed the tier-2 sink.

Mirror of the claude #23 guard (``test_exchange_recorder_http_provisional_finalize``). Codex
persisted tier-1 fine but never called ``emit_to_index``, so a real codex run captured ZERO tier-2
rows (wire_exchange) despite tier-1 working — the silent #23 symptom, codex side. The provisional
row is request-only (no ``entry.res``) and may be DELETED on an abandoned turn, so the sink must
fire once at FINALIZE, never at provisional creation (feeding the provisional would orphan the
tier-2 row + dangle its raw_dir).
"""

from typing import TYPE_CHECKING

from mitmproxy import websocket
from wsproto.frame_protocol import Opcode

from transport_matters.addon import TransportMattersAddon
from transport_matters.codex.test_transport_support import _codex_flow
from transport_matters.storage import get_storage
from transport_matters.storage.exchange_sink import clear_exchange_sink, set_exchange_sink

if TYPE_CHECKING:
    from transport_matters.storage.base import ExchangeArtifacts, IndexEntry

pytest_plugins = ("transport_matters.codex.test_transport_support",)


async def test_codex_finalize_feeds_tier2_sink_once_at_finalize() -> None:
    captured: list[tuple[IndexEntry, ExchangeArtifacts]] = []
    set_exchange_sink(lambda entry, artifacts: captured.append((entry, artifacts)))
    try:
        addon = TransportMattersAddon()
        flow = _codex_flow()
        assert flow.websocket is not None

        addon.websocket_start(flow)
        flow.websocket.messages.append(
            websocket.WebSocketMessage(
                Opcode.TEXT,
                True,
                b'{"type":"response.create","model":"gpt-5-codex","instructions":"first"}',
            )
        )
        await addon.websocket_message(flow)

        # The provisional row is persisted request-only (no response yet); the tier-2 sink must NOT
        # fire here (build_wire_job needs entry.res, and an abandoned provisional gets deleted).
        storage = await get_storage()
        provisional = await storage.read_index(limit=10, offset=0)
        assert len(provisional) == 1
        assert provisional[0].res is None
        assert captured == []

        flow.websocket.messages.append(
            websocket.WebSocketMessage(
                Opcode.TEXT, False, b'{"type":"response.output_text.delta","delta":"hello"}'
            )
        )
        await addon.websocket_message(flow)

        flow.websocket.messages.append(
            websocket.WebSocketMessage(
                Opcode.TEXT,
                False,
                b'{"type":"response.completed","response":{"status":"completed"}}',
            )
        )
        await addon.websocket_message(flow)

        # Finalize feeds the tier-2 sink exactly once, with the completed (response-bearing) exchange.
        assert len(captured) == 1
        entry, artifacts = captured[0]
        finalized = (await storage.read_index(limit=10, offset=0))[0]
        assert entry.id == finalized.id
        assert entry.res is not None
        assert entry.res.stop_reason == "completed"
        assert artifacts.response_ir is not None
        assert artifacts.response_ir.provider == "codex"
    finally:
        clear_exchange_sink()
