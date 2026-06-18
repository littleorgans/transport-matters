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
ResourceRelation = Literal[
    "attached",
    "read",
    "written",
    "mentioned",
    "generated",
    "wire-evidence",
    "native-record",
]
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
    workspace_id: str
    provider: str
    harness: str | None
    status: str
    title: str | None
    purpose: str
    visibility: str
    lineage: dict[str, int | str | None]
    created_at: str | None
    last_activity_at: str

    @classmethod
    def from_row(cls, row: SessionRow) -> SessionHeader:
        last_activity_at = row.updated_at or row.created_at or row.started_at
        return cls(
            session_id=row.session_id,
            workspace_id=f"{row.workspace_slug}/{row.workspace_hash}",
            provider=row.provider,
            harness=row.harness,
            status=str(row.status),
            title=row.title,
            purpose=str(row.session_purpose),
            visibility=str(row.session_visibility),
            lineage={
                "parentSessionId": row.parent_session_id,
                "forkedAtSeq": row.forked_at_seq,
                "forkedAtTurn": None,
            },
            created_at=None if row.created_at is None else row.created_at.isoformat(),
            last_activity_at=last_activity_at.isoformat(),
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
    harness: str
    title: str
    status: SessionStatus
    first_seq: int | None
    last_seq: int | None


class MessageItem(TimelineModel):
    kind: Literal["message"] = "message"
    id: str
    seq: int
    turn_index: int | None
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
    turn_index: int | None
    ts: str | None
    label: str
    value: str
    badge_tone: BadgeTone
    source: SourceRef


class SubagentItem(TimelineModel):
    kind: Literal["subagent"] = "subagent"
    id: str
    seq: int
    turn_index: int | None
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
    turn_index: int | None
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
    turn_index: int | None
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
