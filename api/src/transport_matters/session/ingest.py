"""Transcript record to Postgres session event mapping."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from transport_matters.ir import (
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
)
from transport_matters.session.artifacts import artifact_hash, inline_artifacts_from_parts
from transport_matters.session.models import (
    EventKind,
    EventRow,
    InlineArtifact,
    SessionPurpose,
    SessionRow,
    SessionVisibility,
)

if TYPE_CHECKING:
    from transport_matters.index.adapters.base import (
        NormalizedTurn,
        RawRecord,
        SessionBinding,
        TurnContext,
    )


SEARCH_TEXT_MAX_BYTES = 262_144
SEARCH_TEXT_TRUNCATION_MARKER = "\n[search_text truncated]"


class RecordProvenance(BaseModel):
    """Absolute byte span for a source transcript record, not persisted."""

    model_config = ConfigDict(frozen=True)

    byte_start: int
    byte_end: int


class EventWrite(BaseModel):
    """One event row plus inline artifacts decoded from that event's normalized IR."""

    model_config = ConfigDict(frozen=True)

    event: EventRow
    artifacts: tuple[InlineArtifact, ...] = Field(default_factory=tuple)
    provenance: RecordProvenance | None = None


class EventBatch(BaseModel):
    """Session writer batch: one session upsert plus ordered event writes."""

    model_config = ConfigDict(frozen=True)

    session: SessionRow
    events: tuple[EventWrite, ...] = Field(default_factory=tuple)


def build_session(
    binding: SessionBinding,
    *,
    session_purpose: SessionPurpose = SessionPurpose.USER,
    session_visibility: SessionVisibility = SessionVisibility.USER_VISIBLE,
) -> SessionRow:
    """Build the session row carried by a transcript cursor binding."""
    return SessionRow(
        session_id=binding.session_id,
        provider=binding.provider,
        harness=binding.harness,
        run_id=binding.run_id,
        cwd=binding.cwd,
        workspace_slug=binding.workspace_slug,
        workspace_hash=binding.workspace_hash,
        native_session_id=binding.native_session_id,
        minted=binding.minted,
        source_descriptor=_descriptor_json(binding.source_descriptor),
        home_dir=binding.home_dir,
        template_provenance=binding.template_provenance,
        session_purpose=session_purpose,
        session_visibility=session_visibility,
        title=binding.title,
        parent_session_id=binding.parent_session_id,
        forked_at_seq=binding.forked_at_seq,
        started_at=_parse_required_datetime(binding.started_at),
    )


def build_event_batch(
    binding: SessionBinding,
    events: list[EventWrite],
    *,
    session_purpose: SessionPurpose = SessionPurpose.USER,
    session_visibility: SessionVisibility = SessionVisibility.USER_VISIBLE,
) -> EventBatch:
    """Build the atomic writer batch for one cursor poll."""
    return EventBatch(
        session=build_session(
            binding,
            session_purpose=session_purpose,
            session_visibility=session_visibility,
        ),
        events=tuple(events),
    )


def build_event(record: RawRecord, turn: NormalizedTurn | None, ctx: TurnContext) -> EventWrite:
    """Map one raw transcript record plus optional normalized turn to a session event write."""
    if turn is None:
        return EventWrite(event=_meta_event(record, ctx))
    ir, artifacts = _turn_ir(turn)
    return EventWrite(
        event=EventRow(
            session_id=turn.session_id,
            seq=turn.seq,
            kind=EventKind.TURN,
            native_turn_id=turn.turn_id,
            parent_native_id=turn.parent_id,
            parent_seq=_parent_seq(turn, ctx),
            run_id=turn.run_id,
            provider=turn.provider,
            harness=turn.harness,
            role=turn.role,
            is_sidechain=turn.is_sidechain,
            ts=_parse_datetime(turn.ts),
            model=turn.model,
            raw=dict(record),
            ir=ir,
            source_path=turn.source_path,
            source_line=turn.source_line,
            search_text=_search_text(turn.parts),
        ),
        artifacts=artifacts,
    )


def _meta_event(record: RawRecord, ctx: TurnContext) -> EventRow:
    binding = ctx.binding
    return EventRow(
        session_id=binding.session_id,
        seq=ctx.seq,
        kind=EventKind.META,
        native_turn_id=_record_id(record),
        run_id=binding.run_id,
        provider=binding.provider,
        harness=binding.harness or binding.provider,
        is_sidechain=False,
        ts=_parse_datetime(_record_timestamp(record)),
        model=ctx.model,
        raw=dict(record),
        ir=None,
        source_path=ctx.source_path,
        source_line=ctx.source_line,
        search_text=None,
    )


def _turn_ir(turn: NormalizedTurn) -> tuple[dict[str, Any], tuple[InlineArtifact, ...]]:
    # Any: normalized IR JSON is provider scoped and intentionally opaque below event-level fields.
    artifacts = tuple(inline_artifacts_from_parts(turn.parts))
    ir = turn.model_dump(mode="json")
    if not artifacts:
        return ir, artifacts
    parts = ir.get("parts")
    if not isinstance(parts, list):
        return ir, artifacts
    redacted_parts = list(parts)
    for artifact in artifacts:
        block_index = artifact.ref.get("block_index")
        if isinstance(block_index, int) and 0 <= block_index < len(redacted_parts):
            redacted_parts[block_index] = {
                "type": "image",
                "artifact_hash": artifact_hash(artifact.data),
                "media_type": artifact.media_type,
            }
    ir["parts"] = redacted_parts
    return ir, artifacts


def _parent_seq(turn: NormalizedTurn, ctx: TurnContext) -> int | None:
    if turn.parent_id is None or turn.parent_id != ctx.parent_id:
        return None
    return ctx.parent_seq


def _record_id(record: RawRecord) -> str | None:
    for key in ("uuid", "id"):
        value = record.get(key)
        if isinstance(value, str):
            return value
    payload = record.get("payload")
    if isinstance(payload, dict):
        for key in ("id", "item_id"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
    return None


def _record_timestamp(record: RawRecord) -> str | None:
    value = record.get("timestamp")
    if isinstance(value, str):
        return value
    payload = record.get("payload")
    if isinstance(payload, dict):
        value = payload.get("timestamp")
        if isinstance(value, str):
            return value
    return None


def _descriptor_json(value: str | None) -> dict[str, Any] | None:
    # Any: descriptor JSON is the persisted TranscriptSource shape.
    if value is None:
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {"raw": value}
    return decoded if isinstance(decoded, dict) else {"raw": value}


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_required_datetime(value: str | None) -> datetime:
    return _parse_datetime(value) or datetime.fromtimestamp(0, tz=UTC)


def _search_text(parts: list[Any]) -> str | None:
    # Any: ContentBlock is an annotated union, and this helper accepts the runtime union members.
    chunks: list[str] = []
    for part in parts:
        _append_search_text(part, chunks)
    text = "\n".join(chunks)
    return _cap_search_text(text) if text else None


def _cap_search_text(text: str) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= SEARCH_TEXT_MAX_BYTES:
        return text

    marker = SEARCH_TEXT_TRUNCATION_MARKER.encode("utf-8")
    content_budget = SEARCH_TEXT_MAX_BYTES - len(marker)
    if content_budget <= 0:
        return marker[:SEARCH_TEXT_MAX_BYTES].decode("utf-8", errors="ignore")
    return encoded[:content_budget].decode("utf-8", errors="ignore") + SEARCH_TEXT_TRUNCATION_MARKER


def _append_search_text(part: Any, chunks: list[str]) -> None:
    # Any: ContentBlock is an annotated union, and isinstance narrows only the known members here.
    if isinstance(part, TextBlock | ThinkingBlock):
        chunks.append(part.text)
    elif isinstance(part, ToolUseBlock):
        chunks.append(part.name)
        if part.input:
            chunks.append(json.dumps(part.input, sort_keys=True, default=str))
    elif isinstance(part, ToolResultBlock):
        for nested in part.content:
            _append_search_text(nested, chunks)
    elif isinstance(part, UnknownBlock):
        chunks.append(json.dumps(part.raw, sort_keys=True, default=str))
