from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast, get_args

import pytest
from pydantic import ValidationError

from transport_matters.codex.events import (
    CodexDerivationCursor,
    CodexEventSource,
    CodexOpenAssistantItem,
    CodexOpenToolCall,
    CodexSemanticEvent,
    CodexSemanticEventKind,
    CodexTerminalCause,
    CodexTransportRef,
    CodexTurnStatus,
    CodexTurnSummary,
)


def _ts(hour: int, minute: int, second: int) -> datetime:
    return datetime(2026, 4, 19, hour, minute, second, tzinfo=UTC)


def _literal_values(alias: object) -> set[str]:
    return set(get_args(getattr(alias, "__value__", alias)))


def _cursor() -> CodexDerivationCursor:
    return CodexDerivationCursor(
        next_message_index=8,
        next_seq=4,
        open_assistant_items={
            "msg_b": CodexOpenAssistantItem(text="second"),
            "msg_a": CodexOpenAssistantItem(text="first"),
        },
        open_tool_calls={
            "call_b": CodexOpenToolCall(arguments='{"z":2}'),
            "call_a": CodexOpenToolCall(arguments='{"a":1}'),
        },
        terminal_seen=False,
    )


def test_semantic_event_json_is_stable_for_equivalent_input() -> None:
    first = CodexSemanticEvent(
        event_id="evt_000001",
        exchange_id="ex_123",
        session_id="ws_abc",
        turn_id="turn_002",
        seq=1,
        ts=_ts(10, 14, 3),
        source="server",
        kind="assistant_item_completed",
        transport_ref=CodexTransportRef(message_index=23),
        data={
            "summary": {"z": 2, "a": 1},
            "items": [{"y": 2, "x": 1}],
        },
        derivation_version=1,
    )
    second = CodexSemanticEvent(
        event_id="evt_000001",
        exchange_id="ex_123",
        session_id="ws_abc",
        turn_id="turn_002",
        seq=1,
        ts=_ts(10, 14, 3),
        source="server",
        kind="assistant_item_completed",
        transport_ref=CodexTransportRef(message_index=23),
        data={
            "items": [{"x": 1, "y": 2}],
            "summary": {"a": 1, "z": 2},
        },
        derivation_version=1,
    )

    assert first.model_dump_json() == second.model_dump_json()


def test_turn_summary_json_is_stable_for_equivalent_cursor_maps() -> None:
    first = CodexTurnSummary(
        turn_id="turn_002",
        exchange_id="ex_123",
        session_id="ws_abc",
        turn_index=2,
        request_message_index=23,
        terminal_message_index=31,
        terminal_cause="response_completed",
        message_range_start=23,
        message_range_end=31,
        model="codex/gpt-5-codex",
        status="completed",
        stop_reason="completed",
        text_chars=42,
        tool_calls=1,
        started_at=_ts(10, 14, 3),
        ended_at=_ts(10, 14, 8),
        derivation_version=1,
        cursor=_cursor(),
    )
    second = CodexTurnSummary(
        turn_id="turn_002",
        exchange_id="ex_123",
        session_id="ws_abc",
        turn_index=2,
        request_message_index=23,
        terminal_message_index=31,
        terminal_cause="response_completed",
        message_range_start=23,
        message_range_end=31,
        model="codex/gpt-5-codex",
        status="completed",
        stop_reason="completed",
        text_chars=42,
        tool_calls=1,
        started_at=_ts(10, 14, 3),
        ended_at=_ts(10, 14, 8),
        derivation_version=1,
        cursor=CodexDerivationCursor(
            next_message_index=8,
            next_seq=4,
            open_assistant_items={
                "msg_a": CodexOpenAssistantItem(text="first"),
                "msg_b": CodexOpenAssistantItem(text="second"),
            },
            open_tool_calls={
                "call_a": CodexOpenToolCall(arguments='{"a":1}'),
                "call_b": CodexOpenToolCall(arguments='{"z":2}'),
            },
            terminal_seen=False,
        ),
    )

    assert first.model_dump_json() == second.model_dump_json()


def test_event_taxonomy_literals_match_v1_contract() -> None:
    assert _literal_values(CodexEventSource) == {
        "client",
        "server",
        "proxy",
        "operator",
    }
    assert _literal_values(CodexSemanticEventKind) == {
        "turn_started",
        "request_curated",
        "breakpoint_paused",
        "breakpoint_released",
        "assistant_item_completed",
        "tool_call_completed",
        "tool_output_submitted",
        "response_completed",
        "response_failed",
        "turn_finalized",
    }
    assert _literal_values(CodexTurnStatus) == {
        "open",
        "completed",
        "failed",
        "interrupted",
    }
    assert _literal_values(CodexTerminalCause) == {
        "response_completed",
        "response_failed",
        "websocket_close",
    }


def test_turn_summary_rejects_mismatched_terminal_contract() -> None:
    with pytest.raises(ValidationError, match="response_completed terminal_cause"):
        CodexTurnSummary(
            turn_id="turn_002",
            exchange_id="ex_123",
            session_id="ws_abc",
            turn_index=2,
            request_message_index=23,
            terminal_message_index=31,
            terminal_cause="response_failed",
            message_range_start=23,
            message_range_end=31,
            model="codex/gpt-5-codex",
            status="completed",
            stop_reason="completed",
            text_chars=42,
            tool_calls=1,
            started_at=_ts(10, 14, 3),
            ended_at=_ts(10, 14, 8),
            derivation_version=1,
        )


def test_interrupted_turn_requires_close_stop_reason() -> None:
    with pytest.raises(
        ValidationError, match="interrupted turns must carry stop_reason"
    ):
        CodexTurnSummary(
            turn_id="turn_002",
            exchange_id="ex_123",
            session_id="ws_abc",
            turn_index=2,
            request_message_index=23,
            terminal_cause="websocket_close",
            message_range_start=23,
            message_range_end=30,
            model="codex/gpt-5-codex",
            status="interrupted",
            text_chars=42,
            tool_calls=1,
            started_at=_ts(10, 14, 3),
            ended_at=_ts(10, 14, 8),
            derivation_version=1,
        )


def test_interrupted_turn_rejects_terminal_message_index() -> None:
    with pytest.raises(
        ValidationError,
        match="interrupted turns cannot carry terminal_message_index",
    ):
        CodexTurnSummary(
            turn_id="turn_002",
            exchange_id="ex_123",
            session_id="ws_abc",
            turn_index=2,
            request_message_index=23,
            terminal_message_index=30,
            terminal_cause="websocket_close",
            message_range_start=23,
            message_range_end=30,
            model="codex/gpt-5-codex",
            status="interrupted",
            stop_reason="ws_close_1006",
            text_chars=42,
            tool_calls=1,
            started_at=_ts(10, 14, 3),
            ended_at=_ts(10, 14, 8),
            derivation_version=1,
        )


def test_value_object_models_are_frozen() -> None:
    event = CodexSemanticEvent(
        event_id="evt_000001",
        exchange_id="ex_123",
        session_id="ws_abc",
        turn_id="turn_002",
        seq=1,
        ts=_ts(10, 14, 3),
        source="server",
        kind="response_completed",
        transport_ref=CodexTransportRef(message_index=23),
        derivation_version=1,
    )

    with pytest.raises(ValidationError, match="frozen"):
        cast("Any", event).kind = "response_failed"
