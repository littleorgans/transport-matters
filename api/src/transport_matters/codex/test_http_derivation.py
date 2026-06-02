import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from mitmproxy import websocket
from wsproto.frame_protocol import Opcode

from transport_matters.codex.continuity import get_codex_continuity_allocator
from transport_matters.codex.http_derivation import derive_codex_http_turn
from transport_matters.codex.test_transport_support import _codex_flow
from transport_matters.codex.transport import (
    ensure_codex_transport_state,
    record_codex_websocket_message,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from transport_matters.codex.derivation_contract import (
        CodexReplayRequest,
        CodexTurnDerivationContext,
    )


@pytest.fixture(autouse=True)
def _clear_allocator() -> Iterator[None]:
    allocator = get_codex_continuity_allocator()
    allocator.clear()
    yield
    allocator.clear()


def _request_body() -> bytes:
    return json.dumps({"model": "gpt-5-codex"}).encode()


def _response_stream() -> bytes:
    events = [
        {
            "type": "response.output_text.delta",
            "delta": "hello",
        },
        {
            "type": "response.completed",
            "response": {
                "id": "resp-http",
                "status": "completed",
            },
        },
    ]
    return b"".join(f"data: {json.dumps(event)}\n\n".encode() for event in events)


def _codex_headers(
    *,
    session_id: str,
    thread_id: str,
    turn_id: str | None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = {
        "session-id": session_id,
        "thread-id": thread_id,
    }
    if turn_id is not None:
        headers["x-codex-turn-metadata"] = json.dumps({"turn_id": turn_id})
    if extra:
        headers.update(extra)
    return headers


def _capture_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> list[CodexTurnDerivationContext]:
    contexts: list[CodexTurnDerivationContext] = []

    def fake_derive(request: CodexReplayRequest) -> None:
        contexts.append(request.context)

    monkeypatch.setattr(
        "transport_matters.codex.http_derivation.derive_codex_turn_replay",
        fake_derive,
    )
    return contexts


def _derive(
    exchange_id: str,
    *,
    request_headers: dict[str, str] | None,
) -> None:
    derive_codex_http_turn(
        exchange_id=exchange_id,
        raw_request=_request_body(),
        raw_response=_response_stream(),
        request_headers=request_headers,
        model="gpt-5-codex",
        ts=datetime(2026, 5, 14, tzinfo=UTC),
    )


def _record_websocket_turn(
    *,
    session_id: str,
    thread_id: str,
    turn_id: str | None,
) -> None:
    flow = _codex_flow()
    flow.request.headers.update(
        _codex_headers(session_id=session_id, thread_id=thread_id, turn_id=turn_id)
    )
    assert flow.websocket is not None
    ensure_codex_transport_state(flow)
    flow.websocket.messages.append(
        websocket.WebSocketMessage(Opcode.TEXT, True, b'{"type":"response.create"}')
    )

    update = record_codex_websocket_message(flow)

    assert update is not None


def test_http_derivation_uses_current_codex_identity_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts = _capture_contexts(monkeypatch)

    _derive(
        "exchange-1",
        request_headers={
            "session-id": "session-real",
            "thread-id": "thread-real",
            "x-codex-turn-metadata": '{"turn_id":"turn-real"}',
        },
    )

    assert contexts[0].exchange_id == "exchange-1"
    assert contexts[0].session_id == "session-real"
    assert contexts[0].turn_id == "turn-real"
    assert contexts[0].turn_index == 0


def test_http_retry_reuses_prior_websocket_turn_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts = _capture_contexts(monkeypatch)

    _record_websocket_turn(
        session_id="session-1",
        thread_id="thread-1",
        turn_id="turn-1",
    )
    _derive(
        "exchange-http-retry",
        request_headers=_codex_headers(
            session_id="session-1",
            thread_id="thread-1",
            turn_id="turn-1",
        ),
    )

    assert contexts[0].session_id == "session-1"
    assert contexts[0].turn_id == "turn-1"
    assert contexts[0].turn_index == 0


def test_http_next_turn_after_websocket_receives_monotonic_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts = _capture_contexts(monkeypatch)

    _record_websocket_turn(
        session_id="session-1",
        thread_id="thread-1",
        turn_id="turn-1",
    )
    _derive(
        "exchange-http-next",
        request_headers=_codex_headers(
            session_id="session-1",
            thread_id="thread-1",
            turn_id="turn-2",
        ),
    )

    assert contexts[0].session_id == "session-1"
    assert contexts[0].turn_id == "turn-2"
    assert contexts[0].turn_index == 1


def test_http_fallback_keeps_separate_thread_counters_after_websocket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts = _capture_contexts(monkeypatch)

    _record_websocket_turn(
        session_id="session-1",
        thread_id="thread-1",
        turn_id="turn-1",
    )
    _derive(
        "exchange-separate-session",
        request_headers=_codex_headers(
            session_id="session-2",
            thread_id="thread-2",
            turn_id="turn-1",
        ),
    )

    assert contexts[0].session_id == "session-2"
    assert contexts[0].turn_id == "turn-1"
    assert contexts[0].turn_index == 0


def test_http_subagent_thread_diverges_from_parent_session_counter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts = _capture_contexts(monkeypatch)

    _record_websocket_turn(
        session_id="parent-session",
        thread_id="parent-thread",
        turn_id="parent-turn-1",
    )
    _record_websocket_turn(
        session_id="parent-session",
        thread_id="parent-thread",
        turn_id="parent-turn-2",
    )
    _derive(
        "exchange-subagent",
        request_headers=_codex_headers(
            session_id="parent-session",
            thread_id="child-thread",
            turn_id="child-turn-1",
            extra={
                "x-openai-subagent": "review",
                "x-codex-parent-thread-id": "parent-thread",
            },
        ),
    )

    assert contexts[0].session_id == "parent-session"
    assert contexts[0].turn_id == "child-turn-1"
    assert contexts[0].turn_index == 0


def test_http_missing_turn_metadata_after_websocket_is_lossy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts = _capture_contexts(monkeypatch)

    _record_websocket_turn(
        session_id="session-1",
        thread_id="thread-1",
        turn_id="turn-1",
    )
    _derive(
        "exchange-lossy-http",
        request_headers=_codex_headers(
            session_id="session-1",
            thread_id="thread-1",
            turn_id=None,
        ),
    )

    assert contexts[0].session_id == "session-1"
    assert contexts[0].turn_id == "exchange-lossy-http"
    assert contexts[0].turn_index == 1


def test_http_derivation_returns_full_derived_artifacts() -> None:
    derived = derive_codex_http_turn(
        exchange_id="exchange-1",
        raw_request=_request_body(),
        raw_response=_response_stream(),
        request_headers={
            "session-id": "session-real",
            "thread-id": "thread-real",
            "x-codex-turn-metadata": '{"turn_id":"turn-real"}',
        },
        model="gpt-5-codex",
        ts=datetime(2026, 5, 14, tzinfo=UTC),
    )

    assert derived is not None
    assert derived.events
    assert derived.turn.session_id == "session-real"
    assert derived.turn.turn_id == "turn-real"


def test_http_derivation_reuses_retry_and_advances_next_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts = _capture_contexts(monkeypatch)

    for exchange_id, turn_id in (
        ("exchange-ws-retry", "turn-1"),
        ("exchange-http-retry", "turn-1"),
        ("exchange-http-next", "turn-2"),
    ):
        _derive(
            exchange_id,
            request_headers={
                "session-id": "session-1",
                "thread-id": "thread-1",
                "x-codex-turn-metadata": json.dumps({"turn_id": turn_id}),
            },
        )

    assert [context.turn_id for context in contexts] == [
        "turn-1",
        "turn-1",
        "turn-2",
    ]
    assert [context.turn_index for context in contexts] == [0, 0, 1]


def test_http_derivation_marks_missing_turn_metadata_lossy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts = _capture_contexts(monkeypatch)

    _derive(
        "exchange-exact",
        request_headers={
            "session-id": "session-1",
            "thread-id": "thread-1",
            "x-codex-turn-metadata": '{"turn_id":"turn-1"}',
        },
    )
    _derive(
        "exchange-lossy",
        request_headers={
            "session-id": "session-1",
            "thread-id": "thread-1",
        },
    )

    assert contexts[1].session_id == "session-1"
    assert contexts[1].turn_id == "exchange-lossy"
    assert contexts[1].turn_index == 1


def test_http_derivation_preserves_exchange_fallback_without_thread_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts = _capture_contexts(monkeypatch)

    _derive(
        "exchange-without-thread",
        request_headers={
            "session-id": "session-only",
            "x-codex-turn-metadata": '{"turn_id":"turn-1"}',
        },
    )

    assert contexts[0].session_id == "exchange-without-thread"
    assert contexts[0].turn_id == "exchange-without-thread"
    assert contexts[0].turn_index == 0
