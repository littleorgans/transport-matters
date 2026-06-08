from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from transport_matters.session.models import SessionRow

JsonObject = dict[str, Any]
ContentPart = JsonObject
PaneContentRef = JsonObject

MessageRole = Literal["user", "assistant", "system", "tool"]
BadgeTone = Literal["neutral", "trust", "warning"]
OpenPolicy = Literal["auto", "click", "collapsed"]
ResourceRelation = Literal["attached", "read", "written", "mentioned", "generated", "wire-evidence"]
ResourceConfidence = Literal["verified", "inferred", "mentioned"]
SessionStatus = Literal["active", "completed", "archived", "unknown"]
DiagnosticSeverity = Literal["info", "warning", "error"]


def _to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


class TimelineModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_camel,
        frozen=True,
        populate_by_name=True,
    )


class SessionHeader(TimelineModel):
    session_id: str
    provider: str
    cli: str | None
    run_id: str
    cwd: str
    workspace_slug: str
    workspace_hash: str
    native_session_id: str | None
    owner: str
    status: str
    title: str | None
    parent_session_id: str | None
    forked_at_seq: int | None
    started_at: str
    created_at: str | None
    updated_at: str | None

    @classmethod
    def from_row(cls, row: SessionRow) -> SessionHeader:
        return cls(
            session_id=row.session_id,
            provider=row.provider,
            cli=row.cli,
            run_id=row.run_id,
            cwd=row.cwd,
            workspace_slug=row.workspace_slug,
            workspace_hash=row.workspace_hash,
            native_session_id=row.native_session_id,
            owner=row.owner,
            status=str(row.status),
            title=row.title,
            parent_session_id=row.parent_session_id,
            forked_at_seq=row.forked_at_seq,
            started_at=row.started_at.isoformat(),
            created_at=None if row.created_at is None else row.created_at.isoformat(),
            updated_at=None if row.updated_at is None else row.updated_at.isoformat(),
        )


class SourceRef(TimelineModel):
    session_id: str
    seq: int
    event_kind: Literal["turn", "meta"]
    source_path: str | None
    source_line: int | None
    raw_available: bool
    ir_available: bool


class ResourceRef(TimelineModel):
    resource_id: str
    relation: ResourceRelation
    confidence: ResourceConfidence
    block_index: int | None


class Badge(TimelineModel):
    label: str
    value: str | None = None
    tone: BadgeTone = "neutral"


class SubagentRef(TimelineModel):
    subagent_id: str
    session_id: str
    parent_session_id: str
    parent_seq: int | None
    title: str


class SubagentSummary(TimelineModel):
    subagent_id: str
    session_id: str
    parent_session_id: str
    parent_seq: int | None
    provider: str
    cli: str
    title: str
    status: SessionStatus
    first_seq: int | None
    last_seq: int | None


class MessageItem(TimelineModel):
    kind: Literal["message"] = "message"
    id: str
    seq: int
    role: MessageRole
    ts: str | None
    model: str | None
    parts: list[ContentPart]
    resource_refs: list[ResourceRef] = Field(default_factory=list)
    subagent_refs: list[SubagentRef] = Field(default_factory=list)
    badges: list[Badge] = Field(default_factory=list)
    source: SourceRef


class StateItem(TimelineModel):
    kind: Literal["state"] = "state"
    id: str
    seq: int
    ts: str | None
    label: str
    value: str
    badge_tone: BadgeTone
    source: SourceRef


class SubagentItem(TimelineModel):
    kind: Literal["subagent"] = "subagent"
    id: str
    seq: int
    ts: str | None
    title: str
    subagent_ref: SubagentRef
    summary: str | None
    status: SessionStatus
    source: SourceRef


class ContextItem(TimelineModel):
    kind: Literal["context"] = "context"
    id: str
    seq: int
    ts: str | None
    label: str
    summary: str
    resource_refs: list[ResourceRef] = Field(default_factory=list)
    collapsed: bool
    source: SourceRef


class DiagnosticItem(TimelineModel):
    kind: Literal["diagnostic"] = "diagnostic"
    id: str
    seq: int
    ts: str | None
    label: str
    summary: str
    severity: DiagnosticSeverity
    collapsed: Literal[True] = True
    source: SourceRef


TimelineItemType = MessageItem | StateItem | SubagentItem | ContextItem | DiagnosticItem
TimelineItem = Annotated[TimelineItemType, Field(discriminator="kind")]


class FileResourceSummary(TimelineModel):
    kind: Literal["file"] = "file"
    id: str
    title: str
    path: str
    media_type: str | None
    exists: bool
    size_bytes: int | None
    open_mode: Literal["text", "markdown", "image", "binary"]
    content_provenance: Literal["current", "captured"]
    confidence: ResourceConfidence


class InlineResourceSummary(TimelineModel):
    kind: Literal["inline"] = "inline"
    id: str
    title: str
    media_type: str
    artifact_hash: str
    size_bytes: int


class ToolOutputResourceSummary(TimelineModel):
    kind: Literal["tool-output"] = "tool-output"
    id: str
    title: str
    text_preview: str
    source: SourceRef


class WireResourceSummary(TimelineModel):
    kind: Literal["wire"] = "wire"
    id: str
    title: str
    exchange_id: str
    structured_only: bool


class NativeRecordResourceSummary(TimelineModel):
    kind: Literal["native-record"] = "native-record"
    id: str
    title: str
    source: SourceRef


ResourceSummaryType = (
    FileResourceSummary
    | InlineResourceSummary
    | ToolOutputResourceSummary
    | WireResourceSummary
    | NativeRecordResourceSummary
)
ResourceSummary = Annotated[ResourceSummaryType, Field(discriminator="kind")]


class LayoutHint(TimelineModel):
    target: PaneContentRef
    anchor_seq: int | None
    group_id: str | None
    open_policy: OpenPolicy
    priority: int


class TimelineResponse(TimelineModel):
    session: SessionHeader
    items: list[TimelineItem]
    resources: dict[str, ResourceSummary]
    subagents: dict[str, SubagentSummary]
    layout_hints: list[LayoutHint]
    next_from_seq: int | None


class TimelineItemStreamEvent(TimelineModel):
    kind: Literal["timeline-item"] = "timeline-item"
    item: TimelineItem
    resources: dict[str, ResourceSummary] = Field(default_factory=dict)


class SubagentUpdatedStreamEvent(TimelineModel):
    kind: Literal["subagent-updated"] = "subagent-updated"
    subagent: SubagentSummary


class ResourceUpdatedStreamEvent(TimelineModel):
    kind: Literal["resource-updated"] = "resource-updated"
    resource: ResourceSummary


class SessionUpdatedStreamEvent(TimelineModel):
    kind: Literal["session-updated"] = "session-updated"
    session: SessionHeader


TimelineStreamEventType = (
    TimelineItemStreamEvent
    | SubagentUpdatedStreamEvent
    | ResourceUpdatedStreamEvent
    | SessionUpdatedStreamEvent
)
TimelineStreamEvent = Annotated[TimelineStreamEventType, Field(discriminator="kind")]


class TimelineStreamEnvelope(TimelineModel):
    id: str
    revision: int
    emitted_at: str
    event: TimelineStreamEvent
