"""Pure Codex turn derivation engine."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, cast

from transport_matters.codex.derivation_contract import (
    CodexDerivationOperatorFact,
    CodexDerivedTurnArtifacts,
    CodexIncrementalAdvanceRequest,
    CodexReplayRequest,
    CodexTransportCloseFact,
    CodexTransportMessageFact,
    CodexTurnDerivationContext,
    codex_event_ts,
    codex_next_event_seq,
)
from transport_matters.codex.derivation_events import (
    append_codex_semantic_event,
    codex_assistant_item_event_data,
    codex_terminal_event_data,
    codex_tool_call_event_data,
    codex_tool_output_event_data,
    codex_turn_finalized_event_data,
    open_assistant_text_chars,
)
from transport_matters.codex.events import (
    CodexDerivationCursor,
    CodexOpenAssistantItem,
    CodexOpenToolCall,
    CodexSemanticEvent,
    CodexTerminalCause,
    CodexTransportRef,
    CodexTurnStatus,
    CodexTurnSummary,
)
from transport_matters.codex.protocol import (
    CODEX_ANONYMOUS_ASSISTANT_ITEM_ID,
    codex_assistant_completed_item,
    codex_assistant_item_text,
    codex_close_stop_reason,
    codex_iter_tool_output_items,
    codex_reasoning_completed_item,
    codex_reasoning_item_text,
    codex_terminal_status,
    codex_terminal_stop_reason,
    codex_tool_call_arguments_text,
    codex_tool_call_completed_item,
    codex_tool_call_key,
    codex_update_open_assistant_items,
    codex_update_open_tool_calls,
    is_codex_turn_start,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


def derive_codex_turn_replay(
    request: CodexReplayRequest,
) -> CodexDerivedTurnArtifacts | None:
    """Derive semantic turn artifacts by replaying a turn transport slice."""
    return _derive_codex_turn(
        context=request.context,
        transport_messages=request.transport_messages,
        operator_facts=request.operator_facts,
        close=request.close,
        cursor=None,
        started_at=None,
        committed_text_chars=0,
        committed_tool_calls=0,
    )


def derive_codex_turn_incremental(
    request: CodexIncrementalAdvanceRequest,
) -> CodexDerivedTurnArtifacts:
    """Advance an open turn from persisted cursor and summary state."""
    artifacts = _derive_codex_turn(
        context=request.context,
        transport_messages=request.transport_messages,
        operator_facts=request.operator_facts,
        close=request.close,
        cursor=request.cursor,
        started_at=request.started_at,
        committed_text_chars=max(
            0,
            request.text_chars - open_assistant_text_chars(request.cursor.open_assistant_items),
        ),
        committed_tool_calls=request.tool_calls,
    )
    if artifacts is None:
        msg = "incremental advance requires an existing turn"
        raise ValueError(msg)
    return artifacts


@dataclass
class _CodexTurnDerivationState:
    context: CodexTurnDerivationContext
    next_seq: int
    open_assistant_items: dict[str, CodexOpenAssistantItem]
    open_tool_calls: dict[str, CodexOpenToolCall]
    turn_started: bool
    last_message_index: int
    started_at: datetime | None
    committed_text_chars: int
    committed_tool_calls: int
    terminal_status: Literal["completed", "failed"] | None = None
    terminal_message_index: int | None = None
    terminal_ts: datetime | None = None
    terminal_stop_reason: str | None = None
    events: list[CodexSemanticEvent] = field(default_factory=list)

    def append_event(
        self,
        *,
        source: Literal["client", "server", "proxy", "operator"],
        kind: str,
        ts: datetime,
        transport_ref: CodexTransportRef | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.next_seq = append_codex_semantic_event(
            self.events,
            next_seq=self.next_seq,
            context=self.context,
            source=source,
            kind=kind,
            ts=ts,
            transport_ref=transport_ref,
            data=data,
        )


def _derive_codex_turn(
    *,
    context: CodexTurnDerivationContext,
    transport_messages: Sequence[CodexTransportMessageFact],
    operator_facts: Sequence[CodexDerivationOperatorFact],
    close: CodexTransportCloseFact | None,
    cursor: CodexDerivationCursor | None,
    started_at: datetime | None,
    committed_text_chars: int,
    committed_tool_calls: int,
) -> CodexDerivedTurnArtifacts | None:
    state = _initial_derivation_state(
        context=context,
        cursor=cursor,
        started_at=started_at,
        committed_text_chars=committed_text_chars,
        committed_tool_calls=committed_tool_calls,
    )

    for message in transport_messages:
        if not _advance_derivation_state(
            state,
            message=message,
            operator_facts=operator_facts,
        ):
            return None

    return _finalize_derivation_state(state, close=close)


def _initial_derivation_state(
    *,
    context: CodexTurnDerivationContext,
    cursor: CodexDerivationCursor | None,
    started_at: datetime | None,
    committed_text_chars: int,
    committed_tool_calls: int,
) -> _CodexTurnDerivationState:
    next_seq = codex_next_event_seq(cursor)
    turn_started = cursor is not None and (
        cursor.next_message_index > context.request_message_index or next_seq > 1
    )
    last_message_index = (
        cursor.next_message_index - 1 if cursor is not None else context.request_message_index - 1
    )
    return _CodexTurnDerivationState(
        context=context,
        next_seq=next_seq,
        open_assistant_items=dict((cursor.open_assistant_items if cursor else {}).items()),
        open_tool_calls=dict((cursor.open_tool_calls if cursor else {}).items()),
        turn_started=turn_started,
        last_message_index=last_message_index,
        started_at=started_at,
        committed_text_chars=committed_text_chars,
        committed_tool_calls=committed_tool_calls,
    )


def _advance_derivation_state(
    state: _CodexTurnDerivationState,
    *,
    message: CodexTransportMessageFact,
    operator_facts: Sequence[CodexDerivationOperatorFact],
) -> bool:
    if state.terminal_status is not None:
        msg = "transport slice cannot contain messages after the terminal boundary"
        raise ValueError(msg)

    state.last_message_index = message.message_index
    if message.dropped:
        return state.turn_started or message.message_index != state.context.request_message_index

    payload = message.payload_json if isinstance(message.payload_json, dict) else None
    if not state.turn_started:
        return _try_start_derivation_state(
            state,
            message=message,
            payload=payload,
            operator_facts=operator_facts,
        )

    if message.direction == "client" and is_codex_turn_start(payload, from_client=True):
        msg = "transport slice cannot contain a nested response.create turn start"
        raise ValueError(msg)

    if payload is not None and message.direction == "server":
        _append_server_payload_events(state, message=message, payload=payload)
    return True


def _try_start_derivation_state(
    state: _CodexTurnDerivationState,
    *,
    message: CodexTransportMessageFact,
    payload: dict[str, Any] | None,
    operator_facts: Sequence[CodexDerivationOperatorFact],
) -> bool:
    if (
        message.direction != "client"
        or message.message_index != state.context.request_message_index
        or not is_codex_turn_start(payload, from_client=True)
    ):
        return False

    state.turn_started = True
    state.started_at = message.ts
    state.append_event(
        source="client",
        kind="turn_started",
        ts=message.ts,
        transport_ref=CodexTransportRef(message_index=message.message_index),
    )
    _append_operator_facts(state, operator_facts=operator_facts)
    _append_submitted_tool_outputs(state, message=message, payload=payload)
    return True


def _append_operator_facts(
    state: _CodexTurnDerivationState,
    *,
    operator_facts: Sequence[CodexDerivationOperatorFact],
) -> None:
    for fact in operator_facts:
        state.append_event(
            source=("proxy" if fact.kind == "request_curated" else "operator"),
            kind=fact.kind,
            ts=codex_event_ts(operator_fact=fact),
            data=fact.data,
        )


def _append_submitted_tool_outputs(
    state: _CodexTurnDerivationState,
    *,
    message: CodexTransportMessageFact,
    payload: dict[str, Any] | None,
) -> None:
    for index, item in codex_iter_tool_output_items(payload):
        state.append_event(
            source="client",
            kind="tool_output_submitted",
            ts=message.ts,
            transport_ref=CodexTransportRef(message_index=message.message_index),
            data=codex_tool_output_event_data(item=item, input_index=index),
        )


def _append_server_payload_events(
    state: _CodexTurnDerivationState,
    *,
    message: CodexTransportMessageFact,
    payload: dict[str, Any],
) -> None:
    codex_update_open_assistant_items(
        payload=payload,
        open_assistant_items=state.open_assistant_items,
    )
    codex_update_open_tool_calls(
        payload=payload,
        open_tool_calls=state.open_tool_calls,
    )

    assistant_item = codex_assistant_completed_item(payload)
    if assistant_item is not None:
        _append_assistant_completion_event(
            state,
            message=message,
            assistant_item=assistant_item,
        )
        return

    reasoning_item = codex_reasoning_completed_item(payload)
    if reasoning_item is not None:
        state.append_event(
            source="server",
            kind="assistant_item_completed",
            ts=message.ts,
            transport_ref=CodexTransportRef(message_index=message.message_index),
            data=codex_assistant_item_event_data(
                reasoning_item,
                text=codex_reasoning_item_text(reasoning_item),
            ),
        )
        return

    tool_call_item = codex_tool_call_completed_item(payload)
    if tool_call_item is not None:
        _append_tool_call_completion_event(
            state,
            message=message,
            tool_call_item=tool_call_item,
        )
        return

    terminal_status = codex_terminal_status(payload, from_client=False)
    if terminal_status is not None:
        _append_terminal_event(
            state,
            message=message,
            payload=payload,
            terminal_status=terminal_status,
        )


def _append_assistant_completion_event(
    state: _CodexTurnDerivationState,
    *,
    message: CodexTransportMessageFact,
    assistant_item: dict[str, Any],
) -> None:
    item_id = assistant_item.get("id")
    anonymous_text = state.open_assistant_items.get(
        CODEX_ANONYMOUS_ASSISTANT_ITEM_ID,
        CodexOpenAssistantItem(),
    ).text
    text = (
        codex_assistant_item_text(assistant_item)
        or state.open_assistant_items.get(
            cast("str", item_id or ""),
            CodexOpenAssistantItem(),
        ).text
        or anonymous_text
    )
    if isinstance(item_id, str) and item_id:
        state.open_assistant_items.pop(item_id, None)
    if anonymous_text:
        state.open_assistant_items.pop(CODEX_ANONYMOUS_ASSISTANT_ITEM_ID, None)
    state.committed_text_chars += len(text)
    state.append_event(
        source="server",
        kind="assistant_item_completed",
        ts=message.ts,
        transport_ref=CodexTransportRef(message_index=message.message_index),
        data=codex_assistant_item_event_data(assistant_item, text=text),
    )


def _append_tool_call_completion_event(
    state: _CodexTurnDerivationState,
    *,
    message: CodexTransportMessageFact,
    tool_call_item: dict[str, Any],
) -> None:
    call_key = codex_tool_call_key(tool_call_item)
    arguments = ""
    if call_key is not None:
        arguments = state.open_tool_calls.get(call_key, CodexOpenToolCall()).arguments
        state.open_tool_calls.pop(call_key, None)
    final_arguments = codex_tool_call_arguments_text(tool_call_item)
    if final_arguments:
        arguments = final_arguments
    state.committed_tool_calls += 1
    state.append_event(
        source="server",
        kind="tool_call_completed",
        ts=message.ts,
        transport_ref=CodexTransportRef(message_index=message.message_index),
        data=codex_tool_call_event_data(tool_call_item, arguments=arguments),
    )


def _append_terminal_event(
    state: _CodexTurnDerivationState,
    *,
    message: CodexTransportMessageFact,
    payload: dict[str, Any],
    terminal_status: Literal["completed", "failed"],
) -> None:
    state.terminal_status = terminal_status
    state.terminal_message_index = message.message_index
    state.terminal_ts = message.ts
    state.terminal_stop_reason = (
        codex_terminal_stop_reason(payload, from_client=False) or terminal_status
    )
    state.append_event(
        source="server",
        kind="response_completed" if terminal_status == "completed" else "response_failed",
        ts=message.ts,
        transport_ref=CodexTransportRef(message_index=message.message_index),
        data=codex_terminal_event_data(
            payload=payload,
            stop_reason=state.terminal_stop_reason,
        ),
    )


def _finalize_derivation_state(
    state: _CodexTurnDerivationState,
    *,
    close: CodexTransportCloseFact | None,
) -> CodexDerivedTurnArtifacts | None:
    if not state.turn_started or state.started_at is None:
        return None

    summary_text_chars = state.committed_text_chars + open_assistant_text_chars(
        state.open_assistant_items
    )
    finalized_tool_calls = state.committed_tool_calls + len(state.open_tool_calls)

    if state.terminal_status is not None:
        return _terminal_artifacts(
            state,
            text_chars=summary_text_chars,
            tool_calls=finalized_tool_calls,
        )
    if close is not None:
        return _closed_artifacts(
            state,
            close=close,
            text_chars=summary_text_chars,
            tool_calls=finalized_tool_calls,
        )
    return _open_artifacts(state, text_chars=summary_text_chars)


def _terminal_artifacts(
    state: _CodexTurnDerivationState,
    *,
    text_chars: int,
    tool_calls: int,
) -> CodexDerivedTurnArtifacts:
    terminal_status = cast("Literal['completed', 'failed']", state.terminal_status)
    stop_reason = state.terminal_stop_reason or terminal_status
    terminal_cause: CodexTerminalCause = (
        "response_completed" if terminal_status == "completed" else "response_failed"
    )
    state.append_event(
        source="proxy",
        kind="turn_finalized",
        ts=cast("datetime", state.terminal_ts),
        data=codex_turn_finalized_event_data(
            status=terminal_status,
            terminal_cause=terminal_cause,
            stop_reason=stop_reason,
            text_chars=text_chars,
            tool_calls=tool_calls,
        ),
    )
    turn = _build_turn_summary(
        state,
        status=terminal_status,
        text_chars=text_chars,
        tool_calls=tool_calls,
        terminal_message_index=state.terminal_message_index,
        terminal_cause=terminal_cause,
        stop_reason=stop_reason,
        ended_at=cast("datetime", state.terminal_ts),
    )
    return CodexDerivedTurnArtifacts(events=tuple(state.events), turn=turn)


def _closed_artifacts(
    state: _CodexTurnDerivationState,
    *,
    close: CodexTransportCloseFact,
    text_chars: int,
    tool_calls: int,
) -> CodexDerivedTurnArtifacts:
    stop_reason = codex_close_stop_reason(close.close_code)
    state.append_event(
        source="proxy",
        kind="turn_finalized",
        ts=close.ts,
        data=codex_turn_finalized_event_data(
            status="interrupted",
            terminal_cause="websocket_close",
            stop_reason=stop_reason,
            text_chars=text_chars,
            tool_calls=tool_calls,
            close_code=close.close_code,
        ),
    )
    turn = _build_turn_summary(
        state,
        status="interrupted",
        text_chars=text_chars,
        tool_calls=tool_calls,
        terminal_cause="websocket_close",
        stop_reason=stop_reason,
        ended_at=close.ts,
    )
    return CodexDerivedTurnArtifacts(events=tuple(state.events), turn=turn)


def _open_artifacts(
    state: _CodexTurnDerivationState,
    *,
    text_chars: int,
) -> CodexDerivedTurnArtifacts:
    open_cursor = CodexDerivationCursor(
        next_message_index=state.last_message_index + 1,
        next_seq=state.next_seq,
        open_assistant_items=state.open_assistant_items,
        open_tool_calls=state.open_tool_calls,
        terminal_seen=False,
    )
    turn = _build_turn_summary(
        state,
        status="open",
        text_chars=text_chars,
        tool_calls=state.committed_tool_calls,
        cursor=open_cursor,
    )
    return CodexDerivedTurnArtifacts(events=tuple(state.events), turn=turn)


def _build_turn_summary(
    state: _CodexTurnDerivationState,
    *,
    status: CodexTurnStatus,
    text_chars: int,
    tool_calls: int,
    terminal_message_index: int | None = None,
    terminal_cause: CodexTerminalCause | None = None,
    stop_reason: str | None = None,
    ended_at: datetime | None = None,
    cursor: CodexDerivationCursor | None = None,
) -> CodexTurnSummary:
    return CodexTurnSummary(
        turn_id=state.context.turn_id,
        exchange_id=state.context.exchange_id,
        session_id=state.context.session_id,
        turn_index=state.context.turn_index,
        request_message_index=state.context.request_message_index,
        terminal_message_index=terminal_message_index,
        terminal_cause=terminal_cause,
        message_range_start=state.context.request_message_index,
        message_range_end=state.last_message_index,
        model=state.context.model,
        status=status,
        stop_reason=stop_reason,
        text_chars=text_chars,
        tool_calls=tool_calls,
        started_at=cast("datetime", state.started_at),
        ended_at=ended_at,
        derivation_version=state.context.derivation_version,
        cursor=cursor,
    )


__all__ = [
    "derive_codex_turn_incremental",
    "derive_codex_turn_replay",
]
