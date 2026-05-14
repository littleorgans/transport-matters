from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from transport_matters import exchange_recorder as recorder
from transport_matters.api.v1.exchanges import get_exchange
from transport_matters.codex.derivation_contract import CodexDerivedTurnArtifacts
from transport_matters.codex.test_derivation_support import (
    make_completed_turn,
    make_event,
)
from transport_matters.storage import CodexTurnListSummary, get_storage
from transport_matters.test_exchange_recorder_http_provisional import (
    _Flow,
    _make_codex_state,
    _make_response_body,
    _Response,
)
from transport_matters.test_exchange_recorder_support import (
    reset_exchange_recorder_runtime_state,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Generator
    from pathlib import Path

    from mitmproxy import http


@pytest.fixture(autouse=True)
def _reset_runtime_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None]:
    yield from reset_exchange_recorder_runtime_state(tmp_path, monkeypatch)


def _derived_artifacts(exchange_id: str) -> CodexDerivedTurnArtifacts:
    turn = make_completed_turn(
        exchange_id=exchange_id,
        session_id="session-1",
        turn_id="turn-1",
        turn_index=0,
    )
    return CodexDerivedTurnArtifacts(
        events=(
            make_event(
                1,
                "turn_started",
                turn.started_at,
                exchange_id=exchange_id,
                session_id=turn.session_id,
                turn_id=turn.turn_id,
            ),
        ),
        turn=turn,
    )


async def _persist_fresh(flow: http.HTTPFlow) -> bool:
    return await recorder._persist_http_exchange(flow, _make_codex_state(), None)


async def _persist_provisional(flow: http.HTTPFlow) -> bool:
    state = _make_codex_state()
    exchange_id = await recorder._persist_http_provisional_exchange(flow, state)
    assert exchange_id is not None
    state.provisional_exchange_id = exchange_id
    return await recorder._finalize_http_provisional_exchange(flow, state, None)


@pytest.mark.parametrize("persist", [_persist_fresh, _persist_provisional])
async def test_persist_http_exchange_stores_codex_derived_sidecars(
    monkeypatch: pytest.MonkeyPatch,
    persist: Callable[[http.HTTPFlow], Awaitable[bool]],
) -> None:
    def fake_derive_codex_http_turn(**kwargs: Any) -> CodexDerivedTurnArtifacts:
        return _derived_artifacts(cast("str", kwargs["exchange_id"]))

    monkeypatch.setattr(
        "transport_matters.codex.http_derivation.derive_codex_http_turn",
        fake_derive_codex_http_turn,
    )
    flow = cast("http.HTTPFlow", _Flow())
    cast("_Flow", flow).response = _Response(_make_response_body())

    assert await persist(flow) is True
    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    artifacts = await storage.read_exchange(entries[0].id)

    assert artifacts.events is not None
    assert artifacts.turn is not None
    assert entries[0].codex_turn == CodexTurnListSummary.from_turn(artifacts.turn)
    detail = await get_exchange(entries[0].id, storage)
    assert detail.events == artifacts.events
    assert detail.turn == artifacts.turn
