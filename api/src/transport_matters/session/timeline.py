from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING, Any

from transport_matters.session.timeline_models import (
    Badge,
    ContentPart,
    ContextItem,
    DiagnosticItem,
    JsonObject,
    LayoutHint,
    MessageItem,
    MessageRole,
    NativeRecordResourceSummary,
    ResourceRef,
    ResourceSummaryType,
    SessionHeader,
    SessionStatus,
    SourceRef,
    StateItem,
    SubagentItem,
    SubagentRef,
    SubagentSummary,
    TimelineItemType,
    TimelineResponse,
)

if TYPE_CHECKING:
    from transport_matters.session.models import ChildSessionRow, EventRow, SessionRow

_CONTEXT_LABELS: dict[str, str] = {
    "attachment.skill_listing": "Skill listing",
    "attachment.deferred_tools_delta": "Deferred tools delta",
    "attachment.mcp_instructions_delta": "MCP instructions delta",
    "attachment.hook_additional_context": "Hook context",
    "file-history-snapshot": "File history snapshot",
    "event_msg": "Progress event",
}
_DIAGNOSTIC_LABELS: dict[str, str] = {
    "attachment.hook_success": "Hook success",
    "system.stop_hook_summary": "Stop hook summary",
}
_STATE_LABELS: dict[str, str] = {
    "attachment.output_style": "Output style",
    "mode": "Mode",
    "permission-mode": "Permission mode",
}
_NO_ITEM_META_KEYS = {"last-prompt", "ai-title", "session_meta", "turn_context"}
_ROLE_ALIASES: dict[str, MessageRole] = {
    "user": "user",
    "assistant": "assistant",
    "system": "system",
    "tool": "tool",
    "tool_result": "tool",
}


def project_timeline(
    *,
    session: SessionRow,
    events: list[EventRow],
    child_sessions: list[ChildSessionRow] | tuple[ChildSessionRow, ...] = (),
    include_resources: bool = True,
    include_debug: bool = False,
    next_from_seq: int | None = None,
) -> TimelineResponse:
    items: list[TimelineItemType] = []
    resources: dict[str, ResourceSummaryType] = {}
    subagents: dict[str, SubagentSummary] = {}
    layout_hints: list[LayoutHint] = []
    messages_by_seq: dict[int, MessageItem] = {}
    last_message: MessageItem | None = None
    sidechain_groups: dict[str, list[EventRow]] = {}

    for row in events:
        if row.kind == "turn":
            if row.is_sidechain:
                sidechain_groups.setdefault(_sidechain_root_id(row), []).append(row)
                continue
            message = _message_item(row)
            items.append(message)
            messages_by_seq[row.seq] = message
            last_message = message
            continue

        meta_item = _meta_item(row, last_message)
        if meta_item is not None:
            items.append(meta_item)

    _append_child_subagents(
        session=session,
        child_sessions=child_sessions,
        visible_parent_seqs={row.seq for row in events},
        messages_by_seq=messages_by_seq,
        items=items,
        subagents=subagents,
        layout_hints=layout_hints,
    )
    _append_virtual_sidechains(
        session=session,
        sidechain_groups=sidechain_groups,
        messages_by_seq=messages_by_seq,
        items=items,
        subagents=subagents,
        layout_hints=layout_hints,
    )

    if include_resources and include_debug:
        _append_debug_native_resources(items, resources)

    return TimelineResponse(
        session=SessionHeader.from_row(session),
        items=sorted(items, key=_item_sort_key),
        resources=resources if include_resources else {},
        subagents=subagents,
        layout_hints=layout_hints,
        next_from_seq=next_from_seq,
    )


def _message_item(row: EventRow) -> MessageItem:
    return MessageItem(
        id=f"message:{row.session_id}:{row.seq}",
        seq=row.seq,
        role=_message_role(row.role),
        ts=_ts(row),
        model=row.model,
        parts=_parts(row.ir),
        source=_source_ref(row),
    )


def _meta_item(row: EventRow, last_message: MessageItem | None) -> TimelineItemType | None:
    key = _native_record_key(row.raw)
    if key == "system.turn_duration":
        if last_message is not None:
            last_message.badges.append(
                Badge(label="Turn duration", value=_turn_duration_value(row.raw), tone="neutral")
            )
        return None
    if key in _NO_ITEM_META_KEYS:
        return None
    if key in _STATE_LABELS:
        return StateItem(
            id=f"state:{row.session_id}:{row.seq}",
            seq=row.seq,
            ts=_ts(row),
            label=_STATE_LABELS[key],
            value=_state_value(row.raw, fallback=key),
            badge_tone="trust" if key == "attachment.output_style" else "neutral",
            source=_source_ref(row),
        )
    if key in _CONTEXT_LABELS:
        return ContextItem(
            id=f"context:{row.session_id}:{row.seq}",
            seq=row.seq,
            ts=_ts(row),
            label=_CONTEXT_LABELS[key],
            summary=_summary_value(row.raw, fallback=_CONTEXT_LABELS[key]),
            collapsed=True,
            source=_source_ref(row),
        )
    if key in _DIAGNOSTIC_LABELS:
        return DiagnosticItem(
            id=f"diagnostic:{row.session_id}:{row.seq}",
            seq=row.seq,
            ts=_ts(row),
            label=_DIAGNOSTIC_LABELS[key],
            summary=_summary_value(row.raw, fallback=_DIAGNOSTIC_LABELS[key]),
            severity="info",
            source=_source_ref(row),
        )
    return ContextItem(
        id=f"context:{row.session_id}:{row.seq}",
        seq=row.seq,
        ts=_ts(row),
        label="Native record",
        summary=_summary_value(row.raw, fallback=key),
        collapsed=True,
        source=_source_ref(row),
    )


def _append_child_subagents(
    *,
    session: SessionRow,
    child_sessions: list[ChildSessionRow] | tuple[ChildSessionRow, ...],
    visible_parent_seqs: set[int],
    messages_by_seq: dict[int, MessageItem],
    items: list[TimelineItemType],
    subagents: dict[str, SubagentSummary],
    layout_hints: list[LayoutHint],
) -> None:
    for child in child_sessions:
        if child.forked_at_seq is not None and child.forked_at_seq not in visible_parent_seqs:
            continue
        subagent_ref = _child_subagent_ref(session, child)
        summary = SubagentSummary(
            subagent_id=subagent_ref.subagent_id,
            session_id=subagent_ref.session_id,
            parent_session_id=subagent_ref.parent_session_id,
            parent_seq=subagent_ref.parent_seq,
            mode=subagent_ref.mode,
            provider=child.provider,
            cli=child.cli or "",
            title=subagent_ref.title,
            status=_status(str(child.status)),
            first_seq=child.first_seq,
            last_seq=child.last_seq,
        )
        subagents[summary.subagent_id] = summary
        _attach_subagent_ref(messages_by_seq, subagent_ref)
        seq = child.forked_at_seq if child.forked_at_seq is not None else 0
        items.append(
            SubagentItem(
                id=f"subagent:{session.session_id}:{summary.subagent_id}",
                seq=seq,
                ts=None,
                title=summary.title,
                subagent_ref=subagent_ref,
                summary=None,
                status=summary.status,
                source=_synthetic_source(session.session_id, seq),
            )
        )
        layout_hints.append(_subagent_layout_hint(session.owner, summary, seq))


def _append_virtual_sidechains(
    *,
    session: SessionRow,
    sidechain_groups: dict[str, list[EventRow]],
    messages_by_seq: dict[int, MessageItem],
    items: list[TimelineItemType],
    subagents: dict[str, SubagentSummary],
    layout_hints: list[LayoutHint],
) -> None:
    for root_id, group in sidechain_groups.items():
        ordered = sorted(group, key=lambda item: item.seq)
        first = ordered[0]
        parent_seq = first.parent_seq
        anchor_seq = parent_seq if parent_seq is not None else first.seq
        digest = sha256(root_id.encode("utf-8")).hexdigest()
        subagent_id = f"subagent-sidechain:{session.session_id}:{digest}"
        title = f"Sidechain {first.native_turn_id or first.seq}"
        subagent_ref = SubagentRef(
            subagent_id=subagent_id,
            session_id=session.session_id,
            parent_session_id=session.session_id,
            parent_seq=parent_seq,
            mode="virtual-sidechain",
            title=title,
        )
        summary = SubagentSummary(
            subagent_id=subagent_id,
            session_id=session.session_id,
            parent_session_id=session.session_id,
            parent_seq=parent_seq,
            mode="virtual-sidechain",
            provider=first.provider,
            cli=first.cli,
            title=title,
            status="unknown",
            first_seq=ordered[0].seq,
            last_seq=ordered[-1].seq,
        )
        subagents[subagent_id] = summary
        _attach_subagent_ref(messages_by_seq, subagent_ref)
        items.append(
            SubagentItem(
                id=f"subagent:{session.session_id}:{subagent_id}",
                seq=anchor_seq,
                ts=_ts(first),
                title=title,
                subagent_ref=subagent_ref,
                summary="Inline sidechain record. Normalize to a child session to view it as a pane.",
                status="unknown",
                source=_source_ref(first),
            )
        )
        layout_hints.append(_subagent_layout_hint(session.owner, summary, anchor_seq))


def _append_debug_native_resources(
    items: list[TimelineItemType], resources: dict[str, ResourceSummaryType]
) -> None:
    for item in items:
        if not isinstance(item, ContextItem):
            continue
        resource_id = f"native:{item.source.session_id}:{item.source.seq}"
        resources[resource_id] = NativeRecordResourceSummary(
            id=resource_id,
            title=f"Native record {item.source.seq}",
            source=item.source,
        )
        item.resource_refs.append(
            ResourceRef(
                resource_id=resource_id,
                relation="mentioned",
                confidence="verified",
                block_index=None,
            )
        )


def _child_subagent_ref(session: SessionRow, child: ChildSessionRow) -> SubagentRef:
    title = child.title or child.native_session_id or child.session_id
    return SubagentRef(
        subagent_id=f"subagent-session:{child.session_id}",
        session_id=child.session_id,
        parent_session_id=session.session_id,
        parent_seq=child.forked_at_seq,
        mode="child-session",
        title=title,
    )


def _attach_subagent_ref(messages_by_seq: dict[int, MessageItem], ref: SubagentRef) -> None:
    if ref.parent_seq is None:
        return
    message = messages_by_seq.get(ref.parent_seq)
    if message is not None:
        message.subagent_refs.append(ref)


def _subagent_layout_hint(
    owner: str, summary: SubagentSummary, anchor_seq: int | None
) -> LayoutHint:
    return LayoutHint(
        target={
            "kind": "subagent-timeline",
            "owner": owner,
            "sessionId": summary.session_id,
            "subagentId": summary.subagent_id,
            "parentSessionId": summary.parent_session_id,
            "parentSeq": summary.parent_seq,
        },
        anchor_seq=anchor_seq,
        group_id=summary.parent_session_id,
        open_policy="click",
        priority=50,
    )


def _source_ref(row: EventRow) -> SourceRef:
    return SourceRef(
        session_id=row.session_id,
        seq=row.seq,
        event_kind="meta" if row.kind == "meta" else "turn",
        source_path=row.source_path,
        source_line=row.source_line,
        raw_available=True,
        ir_available=row.ir is not None,
    )


def _synthetic_source(session_id: str, seq: int) -> SourceRef:
    return SourceRef(
        session_id=session_id,
        seq=seq,
        event_kind="meta",
        source_path=None,
        source_line=None,
        raw_available=False,
        ir_available=False,
    )


def _parts(ir: JsonObject | None) -> list[ContentPart]:
    value = None if ir is None else ir.get("parts")
    if not isinstance(value, list):
        value = None if ir is None else ir.get("content")
    if not isinstance(value, list):
        return []
    return [part if isinstance(part, dict) else {"type": "unknown", "raw": part} for part in value]


def _native_record_key(raw: JsonObject) -> str:
    record_type = _string_field(raw, "type") or "unknown"
    attachment = raw.get("attachment")
    attachment_type = None
    if isinstance(attachment, dict):
        attachment_type = _string_field(attachment, "type")
    attachment_type = attachment_type or _string_field(raw, "attachment_type")
    if attachment_type:
        return f"attachment.{attachment_type}"
    subtype = _string_field(raw, "subtype")
    if record_type == "system" and subtype:
        return f"system.{subtype}"
    return record_type


def _state_value(raw: JsonObject, *, fallback: str) -> str:
    attachment = raw.get("attachment")
    candidates: list[Any] = [
        raw.get("value"),
        raw.get("mode"),
        raw.get("permissionMode"),
        raw.get("permission_mode"),
        raw.get("output_style"),
        raw.get("outputStyle"),
    ]
    if isinstance(attachment, dict):
        candidates.extend(
            [
                attachment.get("value"),
                attachment.get("name"),
                attachment.get("output_style"),
                attachment.get("outputStyle"),
            ]
        )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return fallback


def _summary_value(raw: JsonObject, *, fallback: str) -> str:
    attachment = raw.get("attachment")
    candidates: list[Any] = [
        raw.get("summary"),
        raw.get("message"),
        raw.get("text"),
        raw.get("title"),
        raw.get("content"),
    ]
    if isinstance(attachment, dict):
        candidates.extend(
            [
                attachment.get("summary"),
                attachment.get("message"),
                attachment.get("text"),
                attachment.get("name"),
            ]
        )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return _truncate(candidate)
    return fallback


def _turn_duration_value(raw: JsonObject) -> str | None:
    for key in ("duration_ms", "durationMs", "milliseconds", "ms"):
        value = raw.get(key)
        if isinstance(value, int | float):
            return f"{value:g} ms"
    return _summary_value(raw, fallback="completed")


def _sidechain_root_id(row: EventRow) -> str:
    return row.parent_native_id or row.native_turn_id or f"seq:{row.seq}"


def _message_role(role: str | None) -> MessageRole:
    if role is None:
        return "system"
    return _ROLE_ALIASES.get(role, "system")


def _status(value: str) -> SessionStatus:
    if value == "active":
        return "active"
    if value == "completed":
        return "completed"
    if value == "archived":
        return "archived"
    return "unknown"


def _ts(row: EventRow) -> str | None:
    return None if row.ts is None else row.ts.isoformat()


def _string_field(raw: JsonObject, key: str) -> str | None:
    value = raw.get(key)
    return value if isinstance(value, str) and value else None


def _truncate(value: str, limit: int = 180) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _item_sort_key(item: TimelineItemType) -> tuple[int, int, str]:
    priority = {"message": 0, "state": 1, "subagent": 2, "context": 3, "diagnostic": 4}
    return (item.seq, priority[item.kind], item.id)
