from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING, Any, Literal

from transport_matters.session.timeline_models import (
    Badge,
    ContentPart,
    ContextItem,
    DiagnosticItem,
    JsonObject,
    LayoutHint,
    MessageItem,
    MessageRole,
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
    ToolOutputResourceSummary,
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
_TOOL_OUTPUT_LABEL = "Tool output"


def project_timeline(
    *,
    session: SessionRow,
    events: list[EventRow],
    child_sessions: list[ChildSessionRow] | tuple[ChildSessionRow, ...] = (),
    include_resources: bool = True,
    include_debug: bool = False,
    page_from_seq: int | None = None,
    next_from_seq: int | None = None,
) -> TimelineResponse:
    items: list[TimelineItemType] = []
    resources: dict[str, ResourceSummaryType] = {}
    subagents: dict[str, SubagentSummary] = {}
    layout_hints: list[LayoutHint] = []
    messages_by_seq: dict[int, MessageItem] = {}
    message_item_indices_by_seq: dict[int, int] = {}
    last_message_seq: int | None = None
    sidechain_groups: dict[str, list[EventRow]] = {}
    event_kinds_by_seq: dict[int, Literal["turn", "meta"]] = {}

    for row in events:
        event_kinds_by_seq[row.seq] = _source_event_kind(row.kind)
        if row.is_sidechain:
            sidechain_groups.setdefault(_sidechain_root_id(row), []).append(row)
            continue
        if row.kind == "turn":
            message, message_resources = _message_item(row)
            message_item_indices_by_seq[row.seq] = len(items)
            items.append(message)
            messages_by_seq[row.seq] = message
            resources.update(message_resources)
            last_message_seq = row.seq
            continue

        if _native_record_key(row.raw) == "system.turn_duration":
            if last_message_seq is not None:
                _attach_message_badge(
                    items=items,
                    messages_by_seq=messages_by_seq,
                    message_item_indices_by_seq=message_item_indices_by_seq,
                    seq=last_message_seq,
                    badge=Badge(
                        label="Turn duration",
                        value=_turn_duration_value(row.raw),
                        tone="neutral",
                    ),
                )
            continue

        meta_item = _meta_item(row)
        if meta_item is not None:
            items.append(meta_item)

    _append_child_subagents(
        session=session,
        child_sessions=child_sessions,
        visible_parent_seqs={row.seq for row in events},
        visible_seq_window=_seq_window(events, from_seq=page_from_seq),
        event_kinds_by_seq=event_kinds_by_seq,
        messages_by_seq=messages_by_seq,
        message_item_indices_by_seq=message_item_indices_by_seq,
        items=items,
        subagents=subagents,
        layout_hints=layout_hints,
    )
    _append_virtual_sidechains(
        session=session,
        sidechain_groups=sidechain_groups,
        messages_by_seq=messages_by_seq,
        message_item_indices_by_seq=message_item_indices_by_seq,
        items=items,
        subagents=subagents,
        layout_hints=layout_hints,
    )

    return TimelineResponse(
        session=SessionHeader.from_row(session),
        items=sorted(items, key=_item_sort_key),
        resources=resources if include_resources else {},
        subagents=subagents,
        layout_hints=layout_hints,
        next_from_seq=next_from_seq,
    )


def required_timeline_anchor_before_seq(events: list[EventRow]) -> int | None:
    """Return the first live window seq that needs a prior message anchor."""
    last_message_seq: int | None = None
    for row in events:
        if row.is_sidechain:
            continue
        if row.kind == "turn":
            last_message_seq = row.seq
            continue
        if _native_record_key(row.raw) == "system.turn_duration" and last_message_seq is None:
            return row.seq
    return None


def _message_item(row: EventRow) -> tuple[MessageItem, dict[str, ResourceSummaryType]]:
    parts = _parts(row.ir)
    resource_refs, resources = _message_resources(row, parts)
    return MessageItem(
        id=f"message:{row.session_id}:{row.seq}",
        seq=row.seq,
        role=_message_role(row.role),
        ts=_ts(row),
        model=row.model,
        parts=parts,
        resource_refs=resource_refs,
        source=_source_ref(row),
    ), resources


def _meta_item(row: EventRow) -> TimelineItemType | None:
    key = _native_record_key(row.raw)
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


def _message_resources(
    row: EventRow, parts: list[ContentPart]
) -> tuple[list[ResourceRef], dict[str, ResourceSummaryType]]:
    refs: list[ResourceRef] = []
    resources: dict[str, ResourceSummaryType] = {}
    for block_index, part in enumerate(parts):
        if part.get("type") != "tool_result":
            continue
        resource_id = f"tool-output:{row.session_id}:{row.seq}:{block_index}"
        refs.append(
            ResourceRef(
                resource_id=resource_id,
                relation="generated",
                confidence="verified",
                block_index=block_index,
            )
        )
        resources[resource_id] = ToolOutputResourceSummary(
            id=resource_id,
            title=_tool_output_title(part),
            text_preview=_tool_output_preview(part),
            source=_source_ref(row),
        )
    return refs, resources


def _tool_output_title(part: ContentPart) -> str:
    tool_use_id = part.get("tool_use_id")
    if isinstance(tool_use_id, str) and tool_use_id:
        return f"{_TOOL_OUTPUT_LABEL} {tool_use_id}"
    return _TOOL_OUTPUT_LABEL


def _tool_output_preview(part: ContentPart) -> str:
    content = part.get("content")
    if not isinstance(content, list):
        return _TOOL_OUTPUT_LABEL
    chunks: list[str] = []
    for item in content:
        if isinstance(item, str):
            chunks.append(item)
            continue
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                chunks.append(text)
    preview = "\n".join(chunk for chunk in chunks if chunk)
    return _truncate(preview or _TOOL_OUTPUT_LABEL)


def _append_child_subagents(
    *,
    session: SessionRow,
    child_sessions: list[ChildSessionRow] | tuple[ChildSessionRow, ...],
    visible_parent_seqs: set[int],
    visible_seq_window: tuple[int, int] | None,
    event_kinds_by_seq: dict[int, Literal["turn", "meta"]],
    messages_by_seq: dict[int, MessageItem],
    message_item_indices_by_seq: dict[int, int],
    items: list[TimelineItemType],
    subagents: dict[str, SubagentSummary],
    layout_hints: list[LayoutHint],
) -> None:
    for child in child_sessions:
        if not _child_subagent_is_visible(
            child.forked_at_seq,
            visible_parent_seqs=visible_parent_seqs,
            visible_seq_window=visible_seq_window,
        ):
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
        _attach_subagent_ref(
            items=items,
            messages_by_seq=messages_by_seq,
            message_item_indices_by_seq=message_item_indices_by_seq,
            ref=subagent_ref,
        )
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
                source=_synthetic_source(
                    session.session_id,
                    seq,
                    event_kind=event_kinds_by_seq.get(seq, "meta"),
                ),
            )
        )
        layout_hints.append(_subagent_layout_hint(session.owner, summary, seq))


def _append_virtual_sidechains(
    *,
    session: SessionRow,
    sidechain_groups: dict[str, list[EventRow]],
    messages_by_seq: dict[int, MessageItem],
    message_item_indices_by_seq: dict[int, int],
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
        _attach_subagent_ref(
            items=items,
            messages_by_seq=messages_by_seq,
            message_item_indices_by_seq=message_item_indices_by_seq,
            ref=subagent_ref,
        )
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


def _attach_message_badge(
    *,
    items: list[TimelineItemType],
    messages_by_seq: dict[int, MessageItem],
    message_item_indices_by_seq: dict[int, int],
    seq: int,
    badge: Badge,
) -> None:
    message = messages_by_seq.get(seq)
    if message is None:
        return
    updated = message.model_copy(update={"badges": [*message.badges, badge]})
    _replace_message_item(
        items=items,
        messages_by_seq=messages_by_seq,
        message_item_indices_by_seq=message_item_indices_by_seq,
        message=updated,
    )


def _attach_subagent_ref(
    *,
    items: list[TimelineItemType],
    messages_by_seq: dict[int, MessageItem],
    message_item_indices_by_seq: dict[int, int],
    ref: SubagentRef,
) -> None:
    attach_seq = _nearest_message_seq(messages_by_seq, ref.parent_seq)
    if attach_seq is None:
        return
    message = messages_by_seq[attach_seq]
    updated = message.model_copy(update={"subagent_refs": [*message.subagent_refs, ref]})
    _replace_message_item(
        items=items,
        messages_by_seq=messages_by_seq,
        message_item_indices_by_seq=message_item_indices_by_seq,
        message=updated,
    )


def _replace_message_item(
    *,
    items: list[TimelineItemType],
    messages_by_seq: dict[int, MessageItem],
    message_item_indices_by_seq: dict[int, int],
    message: MessageItem,
) -> None:
    messages_by_seq[message.seq] = message
    index = message_item_indices_by_seq.get(message.seq)
    if index is not None:
        items[index] = message


def _nearest_message_seq(
    messages_by_seq: dict[int, MessageItem], parent_seq: int | None
) -> int | None:
    if parent_seq is None:
        return None
    if parent_seq in messages_by_seq:
        return parent_seq
    previous_seqs = [seq for seq in messages_by_seq if seq < parent_seq]
    return max(previous_seqs, default=None)


def _child_subagent_is_visible(
    forked_at_seq: int | None,
    *,
    visible_parent_seqs: set[int],
    visible_seq_window: tuple[int, int] | None,
) -> bool:
    if forked_at_seq is None or forked_at_seq in visible_parent_seqs:
        return True
    if visible_seq_window is None:
        return False
    first_seq, last_seq = visible_seq_window
    return first_seq <= forked_at_seq <= last_seq


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
        event_kind=_source_event_kind(row.kind),
        source_path=row.source_path,
        source_line=row.source_line,
        raw_available=True,
        ir_available=row.ir is not None,
    )


def _synthetic_source(
    session_id: str, seq: int, *, event_kind: Literal["turn", "meta"]
) -> SourceRef:
    return SourceRef(
        session_id=session_id,
        seq=seq,
        event_kind=event_kind,
        source_path=None,
        source_line=None,
        raw_available=False,
        ir_available=False,
    )


def _source_event_kind(kind: object) -> Literal["turn", "meta"]:
    return "meta" if str(kind) == "meta" else "turn"


def _seq_window(events: list[EventRow], *, from_seq: int | None) -> tuple[int, int] | None:
    if not events:
        return None
    seqs = [row.seq for row in events]
    first_seq = from_seq if from_seq is not None else min(seqs)
    return first_seq, max(seqs)


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
