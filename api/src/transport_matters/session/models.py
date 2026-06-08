from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


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
    status: SessionStatus = SessionStatus.ACTIVE
    title: str | None = None
    parent_session_id: str | None = None
    forked_at_seq: int | None = None
    started_at: datetime
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
