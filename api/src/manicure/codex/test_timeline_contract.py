from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from manicure.codex.derivation import CodexReplayRequest, derive_codex_turn_replay

from .test_derivation_support import (
    make_breakpoint_edited_turn_request,
    make_dropped_initial_frame_request,
    make_failed_turn_request,
    make_handshake_failure_request,
    make_interrupted_turn_request,
    make_multi_turn_success_requests,
    make_single_turn_success_request,
    make_tool_result_only_continuation_request,
)


@dataclass(frozen=True)
class ReplayExpectation:
    event_kinds: tuple[str, ...] | None
    transport_refs: tuple[int | None, ...] | None = None
    status: str | None = None
    stop_reason: str | None = None
    terminal_message_index: int | None = None
    terminal_cause: str | None = None
    message_range: tuple[int, int] | None = None
    text_chars: int | None = None
    tool_calls: int | None = None


REPLAY_CASES = [
    (
        "single_turn_success",
        make_single_turn_success_request(),
        ReplayExpectation(
            event_kinds=(
                "turn_started",
                "assistant_item_completed",
                "response_completed",
                "turn_finalized",
            ),
            transport_refs=(0, 1, 2, None),
            status="completed",
            stop_reason="completed",
            terminal_message_index=2,
            terminal_cause="response_completed",
            message_range=(0, 2),
            text_chars=len("hello world"),
            tool_calls=0,
        ),
    ),
    (
        "breakpoint_edited_turn",
        make_breakpoint_edited_turn_request(),
        ReplayExpectation(
            event_kinds=(
                "turn_started",
                "request_curated",
                "breakpoint_paused",
                "breakpoint_released",
                "tool_output_submitted",
                "tool_call_completed",
                "assistant_item_completed",
                "response_completed",
                "turn_finalized",
            ),
            transport_refs=(23, None, None, None, 23, 27, 29, 30, None),
            status="completed",
            stop_reason="completed",
            terminal_message_index=30,
            terminal_cause="response_completed",
            message_range=(23, 30),
            text_chars=5,
            tool_calls=1,
        ),
    ),
    (
        "failed_turn",
        make_failed_turn_request(),
        ReplayExpectation(
            event_kinds=("turn_started", "response_failed", "turn_finalized"),
            transport_refs=(0, 1, None),
            status="failed",
            stop_reason="failed",
            terminal_message_index=1,
            terminal_cause="response_failed",
            message_range=(0, 1),
            text_chars=0,
            tool_calls=0,
        ),
    ),
    (
        "websocket_close_mid_turn",
        make_interrupted_turn_request(),
        ReplayExpectation(
            event_kinds=("turn_started", "turn_finalized"),
            transport_refs=(0, None),
            status="interrupted",
            stop_reason="ws_close_1006",
            terminal_message_index=None,
            terminal_cause="websocket_close",
            message_range=(0, 1),
            text_chars=5,
            tool_calls=0,
        ),
    ),
    (
        "handshake_failure",
        make_handshake_failure_request(),
        ReplayExpectation(event_kinds=None),
    ),
    (
        "dropped_initial_frame",
        make_dropped_initial_frame_request(),
        ReplayExpectation(event_kinds=None),
    ),
    (
        "tool_result_only_continuation",
        make_tool_result_only_continuation_request(),
        ReplayExpectation(
            event_kinds=(
                "turn_started",
                "tool_output_submitted",
                "response_completed",
                "turn_finalized",
            ),
            transport_refs=(0, 0, 1, None),
            status="completed",
            stop_reason="completed",
            terminal_message_index=1,
            terminal_cause="response_completed",
            message_range=(0, 1),
            text_chars=0,
            tool_calls=0,
        ),
    ),
]


def assert_replay_matches_expectation(
    result: Any,
    replay_request: CodexReplayRequest,
    expectation: ReplayExpectation,
) -> None:
    assert result is not None
    assert expectation.event_kinds is not None
    assert expectation.message_range is not None

    assert tuple(event.kind for event in result.events) == expectation.event_kinds
    assert tuple(event.seq for event in result.events) == tuple(
        range(1, len(expectation.event_kinds) + 1)
    )
    assert (
        tuple(
            event.transport_ref.message_index
            if event.transport_ref is not None
            else None
            for event in result.events
        )
        == expectation.transport_refs
    )
    assert all(
        event.exchange_id == replay_request.context.exchange_id
        for event in result.events
    )
    assert all(
        event.session_id == replay_request.context.session_id for event in result.events
    )
    assert all(
        event.turn_id == replay_request.context.turn_id for event in result.events
    )
    assert result.turn.turn_id == replay_request.context.turn_id
    assert result.turn.exchange_id == replay_request.context.exchange_id
    assert result.turn.session_id == replay_request.context.session_id
    assert result.turn.turn_index == replay_request.context.turn_index
    assert (
        result.turn.request_message_index
        == replay_request.context.request_message_index
    )
    assert result.turn.message_range_start == expectation.message_range[0]
    assert result.turn.message_range_end == expectation.message_range[1]
    assert result.turn.status == expectation.status
    assert result.turn.stop_reason == expectation.stop_reason
    assert result.turn.terminal_message_index == expectation.terminal_message_index
    assert result.turn.terminal_cause == expectation.terminal_cause
    assert result.turn.text_chars == expectation.text_chars
    assert result.turn.tool_calls == expectation.tool_calls
    assert result.turn.started_at == replay_request.transport_messages[0].ts

    if replay_request.close is not None:
        assert result.turn.ended_at == replay_request.close.ts
    else:
        assert result.turn.ended_at == replay_request.transport_messages[-1].ts


@pytest.mark.parametrize(
    ("scenario", "replay_request", "expectation"),
    REPLAY_CASES,
)
def test_replay_fixture_contracts(
    scenario: str,
    replay_request: CodexReplayRequest,
    expectation: ReplayExpectation,
) -> None:
    result = derive_codex_turn_replay(replay_request)

    if expectation.event_kinds is None:
        assert result is None, f"{scenario} unexpectedly derived a turn"
        return

    assert_replay_matches_expectation(result, replay_request, expectation)


def test_multi_turn_success_requests_stay_turn_scoped() -> None:
    first_request, second_request = make_multi_turn_success_requests()

    first = derive_codex_turn_replay(first_request)
    second = derive_codex_turn_replay(second_request)

    assert first is not None
    assert second is not None
    assert first.turn.session_id == second.turn.session_id == "ws_multi"
    assert first.turn.exchange_id != second.turn.exchange_id
    assert first.turn.turn_id != second.turn.turn_id
    assert first.turn.turn_index == 0
    assert second.turn.turn_index == 1
    assert first.turn.message_range_start == 0
    assert first.turn.message_range_end == 2
    assert second.turn.message_range_start == 3
    assert second.turn.message_range_end == 5
    assert tuple(
        event.transport_ref.message_index if event.transport_ref is not None else None
        for event in first.events
    ) == (0, 1, 2, None)
    assert tuple(
        event.transport_ref.message_index if event.transport_ref is not None else None
        for event in second.events
    ) == (3, 4, 5, None)
    assert first.events[0].event_id == "evt_000001"
    assert second.events[0].event_id == "evt_000001"
