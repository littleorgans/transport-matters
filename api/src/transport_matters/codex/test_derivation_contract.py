import re

import pytest
from pydantic import ValidationError

from transport_matters.codex.derivation import (
    CODEX_DERIVATION_VERSION,
    SUPPORTED_CODEX_DERIVATION_VERSIONS,
    CodexDerivationOperatorFact,
    CodexDerivedTurnArtifacts,
    CodexReplayRequest,
    UnsupportedCodexDerivationVersionError,
    codex_event_id_for_seq,
    codex_event_ts,
    is_supported_codex_derivation_version,
    require_supported_codex_derivation_version,
    serialize_codex_events_jsonl,
    serialize_codex_turn_json,
)
from transport_matters.codex.events import (
    CodexSemanticEvent,
    CodexTransportRef,
    CodexTurnSummary,
)

from .test_derivation_support import (
    make_completed_turn,
    make_context,
    make_cursor,
    make_event,
    make_message,
    ts,
)


def _open_turn_summary(**overrides: object) -> CodexTurnSummary:
    values: dict[str, object] = {
        "turn_id": "turn_002",
        "exchange_id": "ex_123",
        "session_id": "ws_abc",
        "turn_index": 2,
        "request_message_index": 23,
        "message_range_start": 23,
        "message_range_end": 23,
        "model": "codex/gpt-5-codex",
        "status": "open",
        "started_at": ts(10, 14, 3),
        "derivation_version": CODEX_DERIVATION_VERSION,
    }
    values.update(overrides)
    return CodexTurnSummary(**values)


def test_derivation_version_support_helpers_are_authoritative() -> None:
    assert CODEX_DERIVATION_VERSION == 1
    assert frozenset({1}) == SUPPORTED_CODEX_DERIVATION_VERSIONS
    assert is_supported_codex_derivation_version(1) is True
    assert is_supported_codex_derivation_version(2) is False
    assert require_supported_codex_derivation_version(1) == 1

    with pytest.raises(
        UnsupportedCodexDerivationVersionError,
        match="Supported versions: 1",
    ):
        require_supported_codex_derivation_version(2)


def test_replay_requires_turn_start_message_index() -> None:
    with pytest.raises(
        ValidationError,
        match=re.escape("replay must begin at context.request_message_index"),
    ):
        CodexReplayRequest(
            context=make_context(),
            transport_messages=[
                make_message(
                    24,
                    10,
                    14,
                    4,
                    direction="server",
                    event_type="response.created",
                )
            ],
        )


def test_operator_facts_are_canonicalized_by_timestamp_and_precedence() -> None:
    request = CodexReplayRequest(
        context=make_context(),
        transport_messages=[
            make_message(
                23,
                10,
                14,
                3,
                direction="client",
                event_type="response.create",
            )
        ],
        operator_facts=[
            CodexDerivationOperatorFact(
                kind="breakpoint_released",
                ts=ts(10, 14, 2),
            ),
            CodexDerivationOperatorFact(
                kind="request_curated",
                ts=ts(10, 14, 2),
            ),
            CodexDerivationOperatorFact(
                kind="breakpoint_paused",
                ts=ts(10, 14, 2),
            ),
        ],
    )

    assert tuple(fact.kind for fact in request.operator_facts) == (
        "request_curated",
        "breakpoint_paused",
        "breakpoint_released",
    )


def test_event_identity_and_timestamp_helpers_follow_contract() -> None:
    transport_message = make_message(
        23,
        10,
        14,
        3,
        direction="client",
        event_type="response.create",
    )
    operator_fact = CodexDerivationOperatorFact(
        kind="request_curated",
        ts=ts(10, 14, 2),
    )

    assert codex_event_id_for_seq(17) == "evt_000017"
    assert codex_event_ts(transport_message=transport_message) == ts(10, 14, 3)
    assert codex_event_ts(operator_fact=operator_fact) == ts(10, 14, 2)

    with pytest.raises(ValueError, match="event seq must be >= 1"):
        codex_event_id_for_seq(0)
    with pytest.raises(ValueError, match="exactly one source fact"):
        codex_event_ts()
    with pytest.raises(ValueError, match="exactly one source fact"):
        codex_event_ts(
            transport_message=transport_message,
            operator_fact=operator_fact,
        )


def test_derived_artifacts_require_cursor_for_open_turns() -> None:
    with pytest.raises(ValidationError, match="open turn summaries must carry cursor state"):
        CodexDerivedTurnArtifacts(
            events=(),
            turn=_open_turn_summary(),
        )


def test_derived_artifacts_reject_open_cursor_with_terminal_seen() -> None:
    with pytest.raises(
        ValidationError,
        match="open turn cursors cannot mark terminal_seen",
    ):
        CodexDerivedTurnArtifacts(
            events=(make_event(1, "turn_started", ts(10, 14, 3)),),
            turn=_open_turn_summary(
                cursor=make_cursor(
                    next_message_index=24,
                    next_seq=2,
                    terminal_seen=True,
                )
            ),
        )


@pytest.mark.parametrize(
    ("cursor", "match"),
    [
        (
            make_cursor(next_message_index=25, next_seq=2),
            "open turn cursor.next_message_index must equal turn.message_range_end \\+ 1",
        ),
        (
            make_cursor(next_message_index=24, next_seq=3),
            "open turn cursor.next_seq must equal the next contiguous event seq",
        ),
    ],
)
def test_derived_artifacts_require_open_cursor_resume_geometry(
    cursor: object,
    match: str,
) -> None:
    with pytest.raises(ValidationError, match=match):
        CodexDerivedTurnArtifacts(
            events=(make_event(1, "turn_started", ts(10, 14, 3)),),
            turn=_open_turn_summary(cursor=cursor),
        )


def test_derived_artifacts_reject_unsupported_derivation_version() -> None:
    with pytest.raises(
        ValidationError,
        match="Unsupported Codex derivation version 2",
    ):
        CodexDerivedTurnArtifacts(
            events=(),
            turn=make_completed_turn(derivation_version=2),
        )


def test_serialization_helpers_support_replay_and_incremental_byte_equivalence() -> None:
    first = make_event(1, "turn_started", ts(10, 14, 3))
    second = make_event(2, "response_completed", ts(10, 14, 6))
    replay = CodexDerivedTurnArtifacts(
        events=(first, second),
        turn=make_completed_turn(),
    )
    incremental = CodexDerivedTurnArtifacts(
        events=(second,),
        turn=make_completed_turn(),
    )

    replay_events = serialize_codex_events_jsonl(replay.events)
    incremental_events = serialize_codex_events_jsonl((first,)) + serialize_codex_events_jsonl(
        incremental.events
    )

    assert replay_events == incremental_events
    assert serialize_codex_turn_json(replay.turn) == serialize_codex_turn_json(incremental.turn)


def test_derived_artifacts_reject_noncanonical_event_id() -> None:
    with pytest.raises(
        ValidationError,
        match="event_id must be derived from seq via codex_event_id_for_seq",
    ):
        CodexDerivedTurnArtifacts(
            events=(
                CodexSemanticEvent(
                    event_id="evt_not_canonical",
                    exchange_id="ex_123",
                    session_id="ws_abc",
                    turn_id="turn_002",
                    seq=1,
                    ts=ts(10, 14, 3),
                    source="client",
                    kind="turn_started",
                    transport_ref=CodexTransportRef(message_index=23),
                    derivation_version=CODEX_DERIVATION_VERSION,
                ),
            ),
            turn=make_completed_turn(),
        )
