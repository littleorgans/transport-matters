from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from transport_matters.session.models import (
    SESSION_PURPOSE_VALUES,
    SESSION_VISIBILITY_VALUES,
    EventReadRow,
    SessionListRow,
)
from transport_matters.session.turn_index import turn_indices_by_seq

DEFAULT_SESSIONS_LIMIT = 50
MAX_SESSIONS_LIMIT = 100
PREVIEW_LIMIT = 180

SessionPurposeLiteral = Literal[
    "user",
    "continuation",
    "internal_summary",
    "internal_indexing",
    "internal_eval",
    "system_maintenance",
]
SessionVisibilityLiteral = Literal["user_visible", "hidden", "diagnostic"]


def _to_camel(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(part.capitalize() for part in rest)


class PublicSessionModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        frozen=True,
        populate_by_name=True,
    )


class ApiError(PublicSessionModel):
    code: str
    message: str
    details: object | None = None


class SessionLineage(PublicSessionModel):
    parent_session_id: str | None
    forked_at_seq: int | None
    forked_at_turn: int | None


class SessionView(PublicSessionModel):
    session_id: str
    workspace_id: str
    space_id: str | None
    worktree_id: str | None
    legacy_group: Literal["unassigned"] | None = None
    title: str | None
    status: str
    provider: str
    harness: str
    created_at: datetime
    last_activity_at: datetime
    purpose: SessionPurposeLiteral
    visibility: SessionVisibilityLiteral
    lineage: SessionLineage
    turn_count: int
    inherited_turn_count: int
    last_message_preview: str | None


class ListSessionsResponse(PublicSessionModel):
    items: list[SessionView]
    next_cursor: str | None = None


class TranscriptTextPart(PublicSessionModel):
    type: Literal["text"] = "text"
    text: str


class TranscriptUserBody(PublicSessionModel):
    kind: Literal["user"] = "user"
    parts: list[TranscriptTextPart]


class TranscriptAssistantBody(PublicSessionModel):
    kind: Literal["assistant"] = "assistant"
    parts: list[TranscriptTextPart]


class TranscriptToolUseBody(PublicSessionModel):
    kind: Literal["tool_use"] = "tool_use"
    tool_name: str | None
    input: object | None


class TranscriptToolResultBody(PublicSessionModel):
    kind: Literal["tool_result"] = "tool_result"
    tool_name: str | None
    output: object | None
    is_error: bool


class TranscriptWireInjectedBody(PublicSessionModel):
    kind: Literal["wire_injected"] = "wire_injected"
    label: str
    parts: list[TranscriptTextPart]


TranscriptEventBody = Annotated[
    TranscriptUserBody
    | TranscriptAssistantBody
    | TranscriptToolUseBody
    | TranscriptToolResultBody
    | TranscriptWireInjectedBody,
    Field(discriminator="kind"),
]


class TranscriptResourceRef(PublicSessionModel):
    id: str
    kind: str
    label: str | None = None


class TranscriptEventView(PublicSessionModel):
    seq: int
    turn_index: int | None
    kind: str
    role: str | None
    ts: datetime | None
    body: TranscriptEventBody
    native_payload: dict[str, Any] | None
    resource_refs: list[TranscriptResourceRef] = Field(default_factory=list)


class SessionEventListResponse(PublicSessionModel):
    events: list[TranscriptEventView]
    next_from_seq: int | None = None


def validate_session_purpose(value: str | None) -> str | None:
    if value is not None and value not in SESSION_PURPOSE_VALUES:
        raise ValueError("invalid session purpose")
    return value


def validate_session_visibility(value: str | None) -> str | None:
    if value is not None and value not in SESSION_VISIBILITY_VALUES:
        raise ValueError("invalid session visibility")
    return value


def session_view_from_row(row: SessionListRow) -> SessionView:
    return SessionView(
        session_id=row.session_id,
        workspace_id=workspace_id_from_row(row),
        space_id=str(row.space_id) if row.space_id is not None else None,
        worktree_id=str(row.worktree_id) if row.worktree_id is not None else None,
        legacy_group=_legacy_group_for_session(row),
        title=row.title,
        status=str(row.status),
        provider=row.provider,
        harness=row.harness or "",
        created_at=row.created_at or row.started_at,
        last_activity_at=row.last_activity_at,
        purpose=str(row.session_purpose),
        visibility=str(row.session_visibility),
        lineage=SessionLineage(
            parent_session_id=row.parent_session_id,
            forked_at_seq=row.forked_at_seq,
            forked_at_turn=row.inherited_turn_count if row.parent_session_id else None,
        ),
        turn_count=row.turn_count,
        inherited_turn_count=row.inherited_turn_count,
        last_message_preview=_preview(row.last_message_preview),
    )


def workspace_id_from_row(row: SessionListRow) -> str:
    return f"{row.workspace_slug}/{row.workspace_hash}"


def _legacy_group_for_session(row: SessionListRow) -> Literal["unassigned"] | None:
    if row.cwd == "" and row.space_id is None and row.worktree_id is None:
        return "unassigned"
    return None


def transcript_event_views(
    rows: list[EventReadRow], *, turn_index_offset: int = 0
) -> list[TranscriptEventView]:
    turn_indices = turn_indices_by_seq(rows, offset=turn_index_offset)
    return [transcript_event_view(row, turn_index=turn_indices.get(row.seq)) for row in rows]


def transcript_event_view(row: EventReadRow, *, turn_index: int | None) -> TranscriptEventView:
    return TranscriptEventView(
        seq=row.seq,
        turn_index=turn_index,
        kind=str(row.kind),
        role=row.role,
        ts=row.ts,
        body=_event_body(row),
        native_payload=row.raw,
    )


def _event_body(row: EventReadRow) -> TranscriptEventBody:
    parts = _ir_parts(row.ir)
    tool_use = _first_part(parts, "tool_use")
    if tool_use is not None:
        return TranscriptToolUseBody(
            tool_name=_string_or_none(tool_use.get("name")),
            input=tool_use.get("input"),
        )
    tool_result = _first_part(parts, "tool_result")
    if tool_result is not None:
        return TranscriptToolResultBody(
            tool_name=_string_or_none(tool_result.get("tool_name")),
            output=tool_result.get("content"),
            is_error=bool(tool_result.get("is_error", False)),
        )
    text_parts = _text_parts(parts, fallback=row.search_text)
    if row.kind != "turn" or row.role == "system":
        return TranscriptWireInjectedBody(label=str(row.kind), parts=text_parts)
    if row.role == "user":
        return TranscriptUserBody(parts=text_parts)
    return TranscriptAssistantBody(parts=text_parts)


def _ir_parts(ir: dict[str, Any] | None) -> list[dict[str, Any]]:
    if ir is None:
        return []
    parts = ir.get("parts")
    if not isinstance(parts, list):
        return []
    return [part for part in parts if isinstance(part, dict)]


def _first_part(parts: list[dict[str, Any]], type_: str) -> dict[str, Any] | None:
    return next((part for part in parts if part.get("type") == type_), None)


def _text_parts(parts: list[dict[str, Any]], *, fallback: str | None) -> list[TranscriptTextPart]:
    text_parts = [
        TranscriptTextPart(text=text)
        for part in parts
        if isinstance(text := part.get("text"), str) and text
    ]
    if text_parts:
        return text_parts
    if fallback:
        return [TranscriptTextPart(text=fallback)]
    return []


def _preview(value: str | None) -> str | None:
    if value is None:
        return None
    collapsed = " ".join(value.split())
    if len(collapsed) <= PREVIEW_LIMIT:
        return collapsed
    return collapsed[: PREVIEW_LIMIT - 1].rstrip() + "…"


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) else None
