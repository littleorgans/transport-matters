"""Shared Codex derivation test fact builders."""

from datetime import UTC, datetime

from transport_matters.codex.derivation import (
    CODEX_DERIVATION_VERSION,
    CodexTransportCloseFact,
    CodexTransportMessageFact,
    CodexTurnDerivationContext,
)
from transport_matters.codex.events import (
    CodexDerivationCursor,
    CodexSemanticEvent,
    CodexTransportRef,
    CodexTurnSummary,
)


def ts(hour: int, minute: int, second: int) -> datetime:
    return datetime(2026, 4, 19, hour, minute, second, tzinfo=UTC)


def make_context(**overrides: object) -> CodexTurnDerivationContext:
    values: dict[str, object] = {
        "exchange_id": "ex_123",
        "session_id": "ws_abc",
        "turn_id": "turn_002",
        "turn_index": 2,
        "request_message_index": 23,
        "model": "codex/gpt-5-codex",
        "derivation_version": CODEX_DERIVATION_VERSION,
    }
    values.update(overrides)
    return CodexTurnDerivationContext(**values)


def make_message(
    message_index: int,
    hour: int,
    minute: int,
    second: int,
    *,
    direction: str,
    event_type: str,
    payload_json: dict[str, object] | None = None,
    dropped: bool = False,
) -> CodexTransportMessageFact:
    payload = payload_json or {"type": event_type}
    return CodexTransportMessageFact(
        message_index=message_index,
        ts=ts(hour, minute, second),
        direction=direction,
        event_type=event_type,
        payload_json=payload,
        dropped=dropped,
    )


def make_cursor(**overrides: object) -> CodexDerivationCursor:
    values: dict[str, object] = {
        "next_message_index": 24,
        "next_seq": 2,
        "open_assistant_items": {},
        "open_tool_calls": {},
        "terminal_seen": False,
    }
    values.update(overrides)
    return CodexDerivationCursor(**values)


def make_close(
    hour: int,
    minute: int,
    second: int,
    *,
    close_code: int | None = 1006,
) -> CodexTransportCloseFact:
    return CodexTransportCloseFact(
        ts=ts(hour, minute, second),
        close_code=close_code,
    )


def make_event(
    seq: int,
    kind: str,
    event_ts: datetime,
    **overrides: object,
) -> CodexSemanticEvent:
    values: dict[str, object] = {
        "event_id": f"evt_{seq:06d}",
        "exchange_id": "ex_123",
        "session_id": "ws_abc",
        "turn_id": "turn_002",
        "seq": seq,
        "ts": event_ts,
        "source": "server",
        "kind": kind,
        "transport_ref": CodexTransportRef(message_index=22 + seq),
        "derivation_version": CODEX_DERIVATION_VERSION,
    }
    values.update(overrides)
    return CodexSemanticEvent(**values)


def make_completed_turn(**overrides: object) -> CodexTurnSummary:
    values: dict[str, object] = {
        "turn_id": "turn_002",
        "exchange_id": "ex_123",
        "session_id": "ws_abc",
        "turn_index": 2,
        "request_message_index": 23,
        "terminal_message_index": 25,
        "terminal_cause": "response_completed",
        "message_range_start": 23,
        "message_range_end": 25,
        "model": "codex/gpt-5-codex",
        "status": "completed",
        "stop_reason": "completed",
        "text_chars": 42,
        "tool_calls": 0,
        "started_at": ts(10, 14, 3),
        "ended_at": ts(10, 14, 6),
        "derivation_version": CODEX_DERIVATION_VERSION,
    }
    values.update(overrides)
    return CodexTurnSummary(**values)
