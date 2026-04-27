"""Pure Codex turn derivation engine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from manicure.codex.derivation_contract import (
    CodexDerivationOperatorFact,
    CodexDerivedTurnArtifacts,
    CodexIncrementalAdvanceRequest,
    CodexReplayRequest,
    CodexTransportCloseFact,
    CodexTransportMessageFact,
    CodexTurnDerivationContext,
    codex_event_id_for_seq,
    codex_event_ts,
    codex_next_event_seq,
)
from manicure.codex.events import (
    CodexDerivationCursor,
    CodexOpenAssistantItem,
    CodexOpenToolCall,
    CodexSemanticEvent,
    CodexTerminalCause,
    CodexTransportRef,
    CodexTurnSummary,
)
from manicure.codex.json_utils import json_text_length
from manicure.codex.protocol import (
    CODEX_ANONYMOUS_ASSISTANT_ITEM_ID,
    codex_assistant_completed_item,
    codex_assistant_item_text,
    codex_close_stop_reason,
    codex_iter_tool_output_items,
    codex_reasoning_completed_item,
    codex_reasoning_item_text,
    codex_response_status_reason,
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
            request.text_chars
            - _open_assistant_text_chars(request.cursor.open_assistant_items),
        ),
        committed_tool_calls=request.tool_calls,
    )
    if artifacts is None:
        msg = "incremental advance requires an existing turn"
        raise ValueError(msg)
    return artifacts


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
    next_seq = codex_next_event_seq(cursor)
    open_assistant_items = dict((cursor.open_assistant_items if cursor else {}).items())
    open_tool_calls = dict((cursor.open_tool_calls if cursor else {}).items())
    turn_started = cursor is not None and (
        cursor.next_message_index > context.request_message_index or next_seq > 1
    )
    last_message_index = (
        cursor.next_message_index - 1
        if cursor is not None
        else context.request_message_index - 1
    )
    terminal_status: Literal["completed", "failed"] | None = None
    terminal_message_index: int | None = None
    terminal_ts: datetime | None = None
    terminal_stop_reason: str | None = None
    events: list[CodexSemanticEvent] = []

    for message in transport_messages:
        if terminal_status is not None:
            msg = "transport slice cannot contain messages after the terminal boundary"
            raise ValueError(msg)

        last_message_index = message.message_index
        if message.dropped:
            if (
                not turn_started
                and message.message_index == context.request_message_index
            ):
                return None
            continue

        payload = (
            message.payload_json if isinstance(message.payload_json, dict) else None
        )

        if not turn_started:
            if (
                message.direction != "client"
                or message.message_index != context.request_message_index
                or not is_codex_turn_start(payload, from_client=True)
            ):
                return None
            turn_started = True
            started_at = message.ts
            next_seq = _append_event(
                events,
                next_seq=next_seq,
                context=context,
                source="client",
                kind="turn_started",
                ts=message.ts,
                transport_ref=CodexTransportRef(message_index=message.message_index),
            )
            for fact in operator_facts:
                next_seq = _append_event(
                    events,
                    next_seq=next_seq,
                    context=context,
                    source=("proxy" if fact.kind == "request_curated" else "operator"),
                    kind=fact.kind,
                    ts=codex_event_ts(operator_fact=fact),
                    data=fact.data,
                )
            for index, item in codex_iter_tool_output_items(payload):
                next_seq = _append_event(
                    events,
                    next_seq=next_seq,
                    context=context,
                    source="client",
                    kind="tool_output_submitted",
                    ts=message.ts,
                    transport_ref=CodexTransportRef(
                        message_index=message.message_index
                    ),
                    data=_tool_output_event_data(item=item, input_index=index),
                )
            continue

        if message.direction == "client" and is_codex_turn_start(
            payload, from_client=True
        ):
            msg = "transport slice cannot contain a nested response.create turn start"
            raise ValueError(msg)

        if payload is None:
            continue

        if message.direction == "server":
            codex_update_open_assistant_items(
                payload=payload,
                open_assistant_items=open_assistant_items,
            )
            codex_update_open_tool_calls(
                payload=payload,
                open_tool_calls=open_tool_calls,
            )

            assistant_item = codex_assistant_completed_item(payload)
            if assistant_item is not None:
                item_id = assistant_item.get("id")
                anonymous_text = open_assistant_items.get(
                    CODEX_ANONYMOUS_ASSISTANT_ITEM_ID,
                    CodexOpenAssistantItem(),
                ).text
                text = (
                    codex_assistant_item_text(assistant_item)
                    or open_assistant_items.get(
                        cast("str", item_id or ""),
                        CodexOpenAssistantItem(),
                    ).text
                    or anonymous_text
                )
                if isinstance(item_id, str) and item_id:
                    open_assistant_items.pop(item_id, None)
                if anonymous_text:
                    open_assistant_items.pop(CODEX_ANONYMOUS_ASSISTANT_ITEM_ID, None)
                committed_text_chars += len(text)
                next_seq = _append_event(
                    events,
                    next_seq=next_seq,
                    context=context,
                    source="server",
                    kind="assistant_item_completed",
                    ts=message.ts,
                    transport_ref=CodexTransportRef(
                        message_index=message.message_index
                    ),
                    data=_assistant_item_event_data(assistant_item, text=text),
                )
                continue

            reasoning_item = codex_reasoning_completed_item(payload)
            if reasoning_item is not None:
                text = codex_reasoning_item_text(reasoning_item)
                next_seq = _append_event(
                    events,
                    next_seq=next_seq,
                    context=context,
                    source="server",
                    kind="assistant_item_completed",
                    ts=message.ts,
                    transport_ref=CodexTransportRef(
                        message_index=message.message_index
                    ),
                    data=_assistant_item_event_data(reasoning_item, text=text),
                )
                continue

            tool_call_item = codex_tool_call_completed_item(payload)
            if tool_call_item is not None:
                call_key = codex_tool_call_key(tool_call_item)
                arguments = ""
                if call_key is not None:
                    arguments = open_tool_calls.get(
                        call_key, CodexOpenToolCall()
                    ).arguments
                    open_tool_calls.pop(call_key, None)
                final_arguments = codex_tool_call_arguments_text(tool_call_item)
                if final_arguments:
                    arguments = final_arguments
                committed_tool_calls += 1
                next_seq = _append_event(
                    events,
                    next_seq=next_seq,
                    context=context,
                    source="server",
                    kind="tool_call_completed",
                    ts=message.ts,
                    transport_ref=CodexTransportRef(
                        message_index=message.message_index
                    ),
                    data=_tool_call_event_data(tool_call_item, arguments=arguments),
                )
                continue

            terminal_status = codex_terminal_status(payload, from_client=False)
            if terminal_status is not None:
                terminal_message_index = message.message_index
                terminal_ts = message.ts
                terminal_stop_reason = (
                    codex_terminal_stop_reason(payload, from_client=False)
                    or terminal_status
                )
                next_seq = _append_event(
                    events,
                    next_seq=next_seq,
                    context=context,
                    source="server",
                    kind=(
                        "response_completed"
                        if terminal_status == "completed"
                        else "response_failed"
                    ),
                    ts=message.ts,
                    transport_ref=CodexTransportRef(
                        message_index=message.message_index
                    ),
                    data=_terminal_event_data(
                        payload=payload,
                        stop_reason=terminal_stop_reason,
                    ),
                )

    if not turn_started or started_at is None:
        return None

    summary_text_chars = committed_text_chars + _open_assistant_text_chars(
        open_assistant_items
    )
    finalized_tool_calls = committed_tool_calls + len(open_tool_calls)

    if terminal_status is not None:
        stop_reason = terminal_stop_reason or terminal_status
        status = terminal_status
        terminal_cause: CodexTerminalCause = (
            "response_completed"
            if terminal_status == "completed"
            else "response_failed"
        )
        next_seq = _append_event(
            events,
            next_seq=next_seq,
            context=context,
            source="proxy",
            kind="turn_finalized",
            ts=cast("datetime", terminal_ts),
            data=_turn_finalized_event_data(
                status=status,
                terminal_cause=terminal_cause,
                stop_reason=stop_reason,
                text_chars=summary_text_chars,
                tool_calls=finalized_tool_calls,
            ),
        )
        turn = CodexTurnSummary(
            turn_id=context.turn_id,
            exchange_id=context.exchange_id,
            session_id=context.session_id,
            turn_index=context.turn_index,
            request_message_index=context.request_message_index,
            terminal_message_index=terminal_message_index,
            terminal_cause=terminal_cause,
            message_range_start=context.request_message_index,
            message_range_end=last_message_index,
            model=context.model,
            status=status,
            stop_reason=stop_reason,
            text_chars=summary_text_chars,
            tool_calls=finalized_tool_calls,
            started_at=started_at,
            ended_at=cast("datetime", terminal_ts),
            derivation_version=context.derivation_version,
        )
        return CodexDerivedTurnArtifacts(events=tuple(events), turn=turn)

    if close is not None:
        stop_reason = codex_close_stop_reason(close.close_code)
        next_seq = _append_event(
            events,
            next_seq=next_seq,
            context=context,
            source="proxy",
            kind="turn_finalized",
            ts=close.ts,
            data=_turn_finalized_event_data(
                status="interrupted",
                terminal_cause="websocket_close",
                stop_reason=stop_reason,
                text_chars=summary_text_chars,
                tool_calls=finalized_tool_calls,
                close_code=close.close_code,
            ),
        )
        turn = CodexTurnSummary(
            turn_id=context.turn_id,
            exchange_id=context.exchange_id,
            session_id=context.session_id,
            turn_index=context.turn_index,
            request_message_index=context.request_message_index,
            terminal_cause="websocket_close",
            message_range_start=context.request_message_index,
            message_range_end=last_message_index,
            model=context.model,
            status="interrupted",
            stop_reason=stop_reason,
            text_chars=summary_text_chars,
            tool_calls=finalized_tool_calls,
            started_at=started_at,
            ended_at=close.ts,
            derivation_version=context.derivation_version,
        )
        return CodexDerivedTurnArtifacts(events=tuple(events), turn=turn)

    open_cursor = CodexDerivationCursor(
        next_message_index=last_message_index + 1,
        next_seq=next_seq,
        open_assistant_items=open_assistant_items,
        open_tool_calls=open_tool_calls,
        terminal_seen=False,
    )
    turn = CodexTurnSummary(
        turn_id=context.turn_id,
        exchange_id=context.exchange_id,
        session_id=context.session_id,
        turn_index=context.turn_index,
        request_message_index=context.request_message_index,
        message_range_start=context.request_message_index,
        message_range_end=last_message_index,
        model=context.model,
        status="open",
        text_chars=summary_text_chars,
        tool_calls=committed_tool_calls,
        started_at=started_at,
        derivation_version=context.derivation_version,
        cursor=open_cursor,
    )
    return CodexDerivedTurnArtifacts(events=tuple(events), turn=turn)


def _append_event(
    events: list[CodexSemanticEvent],
    *,
    next_seq: int,
    context: CodexTurnDerivationContext,
    source: Literal["client", "server", "proxy", "operator"],
    kind: str,
    ts: datetime,
    transport_ref: CodexTransportRef | None = None,
    data: dict[str, Any] | None = None,
) -> int:
    events.append(
        CodexSemanticEvent(
            event_id=codex_event_id_for_seq(next_seq),
            exchange_id=context.exchange_id,
            session_id=context.session_id,
            turn_id=context.turn_id,
            seq=next_seq,
            ts=ts,
            source=source,
            kind=cast("Any", kind),
            transport_ref=transport_ref,
            data=data or {},
            derivation_version=context.derivation_version,
        )
    )
    return next_seq + 1


def _tool_output_event_data(
    *,
    item: dict[str, Any],
    input_index: int,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "input_index": input_index,
        "item_type": str(item.get("type", "")),
        "output_chars": json_text_length(item.get("output")),
    }
    call_id = item.get("call_id")
    if isinstance(call_id, str) and call_id:
        data["call_id"] = call_id
    return data


def _assistant_item_event_data(item: dict[str, Any], *, text: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "item_type": str(item.get("type", "")),
        "text_chars": len(text),
    }
    item_id = item.get("id")
    if isinstance(item_id, str) and item_id:
        data["item_id"] = item_id
    phase = item.get("phase")
    if isinstance(phase, str) and phase:
        data["phase"] = phase
    role = item.get("role")
    if isinstance(role, str) and role:
        data["role"] = role
    return data


def _tool_call_event_data(
    item: dict[str, Any],
    *,
    arguments: str,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "item_type": str(item.get("type", "")),
        "arguments_chars": len(arguments),
    }
    call_id = item.get("call_id")
    if not isinstance(call_id, str) or not call_id:
        call_id = item.get("id")
    if isinstance(call_id, str) and call_id:
        data["call_id"] = call_id
    item_id = item.get("id")
    if isinstance(item_id, str) and item_id:
        data["item_id"] = item_id
    tool_name = item.get("name")
    if isinstance(tool_name, str) and tool_name:
        data["tool_name"] = tool_name
    return data


def _terminal_event_data(
    *,
    payload: dict[str, Any],
    stop_reason: str,
) -> dict[str, Any]:
    data: dict[str, Any] = {"stop_reason": stop_reason}
    response = payload.get("response")
    if isinstance(response, dict):
        response_id = response.get("id")
        if isinstance(response_id, str) and response_id:
            data["response_id"] = response_id
        response_status = codex_response_status_reason(response)
        if isinstance(response_status, str) and response_status:
            data["response_status"] = response_status
    return data


def _turn_finalized_event_data(
    *,
    status: str,
    terminal_cause: str,
    stop_reason: str,
    text_chars: int,
    tool_calls: int,
    close_code: int | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "status": status,
        "terminal_cause": terminal_cause,
        "stop_reason": stop_reason,
        "text_chars": text_chars,
        "tool_calls": tool_calls,
    }
    if close_code is not None:
        data["close_code"] = close_code
    return data


def _open_assistant_text_chars(
    open_assistant_items: dict[str, CodexOpenAssistantItem],
) -> int:
    return sum(len(item.text) for item in open_assistant_items.values())


__all__ = [
    "derive_codex_turn_incremental",
    "derive_codex_turn_replay",
]
