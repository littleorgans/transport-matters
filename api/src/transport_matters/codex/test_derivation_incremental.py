from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from transport_matters.codex.derivation import (
    CodexIncrementalAdvanceRequest,
    CodexReplayRequest,
    codex_next_event_seq,
    derive_codex_turn_incremental,
    derive_codex_turn_replay,
    serialize_codex_events_jsonl,
    serialize_codex_turn_json,
)

from .test_derivation_support import (
    make_breakpoint_edited_turn_request,
    make_context,
    make_cursor,
    make_failed_turn_request,
    make_message,
    make_single_turn_success_request,
    make_tool_result_only_continuation_request,
)


def _derive_incrementally(
    replay_request: CodexReplayRequest,
    *,
    cut_points: tuple[int, ...],
) -> tuple[bytes, bytes]:
    cursor = make_cursor(
        next_message_index=replay_request.context.request_message_index,
        next_seq=1,
    )
    started_at = None
    text_chars = 0
    tool_calls = 0
    offset = 0
    events_jsonl = b""
    turn_json: bytes | None = None

    for stop in (*cut_points, len(replay_request.transport_messages)):
        result = derive_codex_turn_incremental(
            CodexIncrementalAdvanceRequest(
                context=replay_request.context,
                cursor=cursor,
                operator_facts=(replay_request.operator_facts if offset == 0 else ()),
                close=(
                    replay_request.close if stop == len(replay_request.transport_messages) else None
                ),
                started_at=started_at,
                text_chars=text_chars,
                tool_calls=tool_calls,
                transport_messages=replay_request.transport_messages[offset:stop],
            )
        )
        events_jsonl += serialize_codex_events_jsonl(result.events)
        turn_json = serialize_codex_turn_json(result.turn)
        started_at = result.turn.started_at
        text_chars = result.turn.text_chars
        tool_calls = result.turn.tool_calls
        offset = stop
        if result.turn.cursor is None:
            break
        cursor = result.turn.cursor

    assert turn_json is not None
    return events_jsonl, turn_json


def test_incremental_advance_requires_open_cursor_boundary() -> None:
    with pytest.raises(
        ValidationError,
        match=re.escape("incremental advance must begin at cursor.next_message_index"),
    ):
        CodexIncrementalAdvanceRequest(
            context=make_context(),
            cursor=make_cursor(next_message_index=24, next_seq=2),
            transport_messages=[
                make_message(
                    25,
                    10,
                    14,
                    5,
                    direction="server",
                    event_type="response.output_text.delta",
                )
            ],
        )

    with pytest.raises(ValueError, match=re.escape("cursor.next_seq must be >= 1")):
        codex_next_event_seq(make_cursor(next_seq=0))


def test_incremental_advance_rejects_terminal_cursor() -> None:
    with pytest.raises(
        ValidationError,
        match=re.escape("incremental advance cannot resume from a terminal cursor"),
    ):
        CodexIncrementalAdvanceRequest(
            context=make_context(),
            cursor=make_cursor(terminal_seen=True),
            transport_messages=[],
        )


def test_incremental_advance_requires_started_at_after_turn_start() -> None:
    with pytest.raises(
        ValidationError,
        match="incremental advance requires started_at once the turn has started",
    ):
        CodexIncrementalAdvanceRequest(
            context=make_context(),
            cursor=make_cursor(next_message_index=24, next_seq=2),
            transport_messages=[],
        )


@pytest.mark.parametrize(
    ("scenario", "replay_request", "cut_points"),
    [
        (
            "single_turn_success",
            make_single_turn_success_request(),
            (1,),
        ),
        (
            "breakpoint_edited_turn",
            make_breakpoint_edited_turn_request(),
            (5,),
        ),
        (
            "failed_turn",
            make_failed_turn_request(),
            (1,),
        ),
        (
            "tool_result_only_continuation",
            make_tool_result_only_continuation_request(),
            (1,),
        ),
    ],
)
def test_incremental_advance_serializes_identically_to_replay(
    scenario: str,
    replay_request: CodexReplayRequest,
    cut_points: tuple[int, ...],
) -> None:
    replay = derive_codex_turn_replay(replay_request)
    assert replay is not None

    incremental_events, incremental_turn = _derive_incrementally(
        replay_request,
        cut_points=cut_points,
    )
    replay_events = serialize_codex_events_jsonl(replay.events)
    replay_turn = serialize_codex_turn_json(replay.turn)

    assert incremental_events == replay_events, (
        f"{scenario} incremental events diverged from replay"
    )
    assert incremental_turn == replay_turn, f"{scenario} incremental turn diverged from replay"
