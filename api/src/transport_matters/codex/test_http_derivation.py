from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from transport_matters.codex.continuity import get_codex_continuity_allocator
from transport_matters.codex.http_derivation import derive_codex_http_turn

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
