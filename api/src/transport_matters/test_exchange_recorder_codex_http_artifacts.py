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


class _SseResponse(_Response):
    def __init__(self) -> None:
        self.headers = {
            "content-type": "text/event-stream",
            "set-cookie": "secret-cookie",
        }
        self.status_code = 200

    def get_text(self) -> str:
        return (
            'data: {"type":"response.output_text.delta","delta":"hi"}\n\n'
            'data: {"type":"response.completed","response":{"status":"completed"}}\n\n'
        )


@pytest.fixture(autouse=True)
def _reset_runtime_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None]:
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


def _codex_http_flow() -> http.HTTPFlow:
    flow = _Flow()
    request = cast("Any", flow.request)
    request.method = "POST"
    request.scheme = "https"
    request.host = "chatgpt.com"
    request.path = "/backend-api/codex/responses"
    request.headers = {
        "authorization": "Bearer secret-token",
        "session-id": "session-1",
        "thread-id": "thread-1",
        "x-codex-turn-metadata": '{"turn_id":"turn-1"}',
    }
    flow.response = _SseResponse()
    return cast("http.HTTPFlow", flow)


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


@pytest.mark.parametrize("persist", [_persist_fresh, _persist_provisional])
async def test_persist_http_exchange_stores_codex_transport_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    persist: Callable[[http.HTTPFlow], Awaitable[bool]],
) -> None:
    def fake_derive_codex_http_turn(**kwargs: Any) -> CodexDerivedTurnArtifacts:
        return _derived_artifacts(cast("str", kwargs["exchange_id"]))

    monkeypatch.setattr(
        "transport_matters.codex.http_derivation.derive_codex_http_turn",
        fake_derive_codex_http_turn,
    )

    assert await persist(_codex_http_flow()) is True

    storage = await get_storage()
    entries = await storage.read_index(limit=10, offset=0)
    artifacts = await storage.read_exchange(entries[0].id)

    assert artifacts.transport is not None
    transport = artifacts.transport
    assert transport.protocol == "http"
    assert transport.request is not None
    assert transport.request.method == "POST"
    assert transport.request.host == "chatgpt.com"
    request_headers = {header.name: header.value for header in transport.request.headers}
    assert request_headers["authorization"] == "Bearer [redacted]"
    assert request_headers["session-id"] == "session-1"
    assert transport.response is not None
    assert transport.response.status_code == 200
    response_headers = {header.name: header.value for header in transport.response.headers}
    assert response_headers["set-cookie"] == "[redacted]"
    assert [message.direction for message in transport.messages] == [
        "client",
        "server",
        "server",
    ]
    assert [message.event_type for message in transport.messages] == [
        "response.create",
        "response.output_text.delta",
        "response.completed",
    ]
    client_payload = transport.messages[0].payload_json
    assert isinstance(client_payload, dict)
    assert client_payload["type"] == "response.create"
    assert "upgrade" not in transport.model_dump(mode="json")
