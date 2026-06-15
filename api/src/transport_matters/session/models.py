from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class SessionPurpose(StrEnum):
    USER = "user"
    CONTINUATION = "continuation"
    INTERNAL_SUMMARY = "internal_summary"
    INTERNAL_INDEXING = "internal_indexing"
    INTERNAL_EVAL = "internal_eval"
    SYSTEM_MAINTENANCE = "system_maintenance"


class SessionVisibility(StrEnum):
    USER_VISIBLE = "user_visible"
    HIDDEN = "hidden"
    DIAGNOSTIC = "diagnostic"


SESSION_PURPOSE_VALUES: Final[tuple[str, ...]] = tuple(item.value for item in SessionPurpose)
SESSION_VISIBILITY_VALUES: Final[tuple[str, ...]] = tuple(item.value for item in SessionVisibility)
USER_HISTORY_PURPOSE_VALUES: Final[tuple[str, ...]] = (
    SessionPurpose.USER.value,
    SessionPurpose.CONTINUATION.value,
)


class EventKind(StrEnum):
    TURN = "turn"
    META = "meta"


JsonObject = dict[str, Any]  # Any: provider transcript JSON is intentionally opaque.


class EventArtifactRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: str
    seq: int
    artifact_hash: str
    ref: JsonObject | None = None
    media_type: str | None = None
    size_bytes: int | None = None


class SessionRow(BaseModel):
    model_config = ConfigDict(frozen=True, use_enum_values=True)

    session_id: str
    provider: str
    cli: str | None = None
    run_id: str
    cwd: str = ""
    workspace_slug: str
    workspace_hash: str
    native_session_id: str | None = None
    minted: bool = False
    source_descriptor: JsonObject | None = None
    home_dir: str | None = None
    owner: str = "local"
    session_purpose: SessionPurpose = SessionPurpose.USER
    session_visibility: SessionVisibility = SessionVisibility.USER_VISIBLE
    status: SessionStatus = SessionStatus.ACTIVE
    title: str | None = None
    parent_session_id: str | None = None
    forked_at_seq: int | None = None
    started_at: datetime
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionListRow(SessionRow):
    model_config = ConfigDict(frozen=True, use_enum_values=True)

    last_activity_at: datetime
    turn_count: int = 0
    inherited_turn_count: int = 0
    last_message_preview: str | None = None


class ChildSessionRow(SessionRow):
    model_config = ConfigDict(frozen=True, use_enum_values=True)

    first_seq: int | None = None
    last_seq: int | None = None


class EventRow(BaseModel):
    model_config = ConfigDict(frozen=True, use_enum_values=True)

    session_id: str
    seq: int
    kind: EventKind = EventKind.TURN
    native_turn_id: str | None = None
    parent_native_id: str | None = None
    parent_seq: int | None = None
    run_id: str
    provider: str
    cli: str
    role: str | None = None
    is_sidechain: bool = False
    ts: datetime | None = None
    model: str | None = None
    raw: JsonObject
    ir: JsonObject | None = None
    source_path: str | None = None
    source_line: int | None = None
    search_text: str | None = None
    created_at: datetime | None = None
    artifacts: tuple[EventArtifactRow, ...] = ()


class DeadLetterWrite(BaseModel):
    """Dead-letter row to persist for a quarantined transcript record or window."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    seq: int | None = None
    scope: Literal["record", "window"] = "record"
    run_id: str
    native_session_id: str | None = None
    provider: str | None = None
    cli: str | None = None
    source_path: str | None = None
    source_line: int | None = None
    event_kind: str | None = None
    byte_start: int
    byte_end: int
    error_sqlstate: str | None = None
    error_class: str
    error_message: str
    raw_excerpt: bytes | None = None
    attempts: int = 1


class EventReadRow(BaseModel):
    model_config = ConfigDict(frozen=True, use_enum_values=True)

    session_id: str
    seq: int
    kind: EventKind = EventKind.TURN
    native_turn_id: str | None = None
    parent_native_id: str | None = None
    parent_seq: int | None = None
    run_id: str
    provider: str
    cli: str
    role: str | None = None
    is_sidechain: bool = False
    ts: datetime | None = None
    model: str | None = None
    raw: JsonObject | None = None
    ir: JsonObject | None = None
    source_path: str | None = None
    source_line: int | None = None
    search_text: str | None = None
    created_at: datetime | None = None


class ArtifactRow(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    hash: str
    media_type: str | None = None
    size_bytes: int
    data: bytes = Field(alias="bytes")
    created_at: datetime | None = None


class InlineArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)

    media_type: str | None = None
    data: bytes
    ref: JsonObject
