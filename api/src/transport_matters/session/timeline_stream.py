from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from transport_matters.session.timeline import project_timeline
from transport_matters.session.timeline_models import (
    ResourceSummaryType,
    ResourceUpdatedStreamEvent,
    SessionHeader,
    SessionUpdatedStreamEvent,
    SourceRef,
    SubagentSummary,
    SubagentUpdatedStreamEvent,
    TimelineItemStreamEvent,
    TimelineItemType,
    TimelineStreamEnvelope,
)

if TYPE_CHECKING:
    from transport_matters.session.models import ChildSessionRow, EventRow, SessionRow


def project_timeline_stream_envelopes(
    *,
    session: SessionRow,
    events: list[EventRow],
    child_sessions: list[ChildSessionRow] | tuple[ChildSessionRow, ...] = (),
    include_resources: bool = True,
    include_debug: bool = False,
    include_session_update: bool = False,
    emitted_at: str | None = None,
    page_from_seq: int | None = None,
) -> list[TimelineStreamEnvelope]:
    projection_revision_seq = max((row.seq for row in events), default=None)
    projection = project_timeline(
        session=session,
        events=events,
        child_sessions=child_sessions,
        include_resources=include_resources,
        include_debug=include_debug,
        page_from_seq=page_from_seq,
    )
    stamp = emitted_at or _emitted_at()
    envelopes: list[TimelineStreamEnvelope] = []
    if include_session_update:
        envelopes.append(_session_updated_envelope(session, projection.session, stamp))
    envelopes.extend(
        _timeline_item_envelope(
            session.session_id,
            item,
            projection.resources,
            stamp,
            revision=_item_revision(
                item_seq=item.seq,
                page_from_seq=page_from_seq,
                projection_revision_seq=projection_revision_seq,
            ),
        )
        for item in projection.items
    )
    envelopes.extend(
        _resource_updated_envelope(session.session_id, resource, stamp)
        for resource in sorted(projection.resources.values(), key=lambda item: item.id)
    )
    envelopes.extend(
        _subagent_updated_envelope(subagent, stamp)
        for subagent in sorted(projection.subagents.values(), key=lambda item: item.subagent_id)
    )
    return envelopes


def _timeline_item_envelope(
    session_id: str,
    item: TimelineItemType,
    resources: dict[str, ResourceSummaryType],
    emitted_at: str,
    *,
    revision: int,
) -> TimelineStreamEnvelope:
    return TimelineStreamEnvelope(
        id=f"timeline:{session_id}:{item.seq}",
        revision=revision,
        emitted_at=emitted_at,
        event=TimelineItemStreamEvent(
            item=item,
            resources=_resources_for_item(item, resources),
        ),
    )


def _item_revision(
    *, item_seq: int, page_from_seq: int | None, projection_revision_seq: int | None
) -> int:
    if (
        page_from_seq is not None
        and projection_revision_seq is not None
        and item_seq < page_from_seq
    ):
        return max(item_seq, projection_revision_seq)
    return item_seq


def _resource_updated_envelope(
    session_id: str, resource: ResourceSummaryType, emitted_at: str
) -> TimelineStreamEnvelope:
    return TimelineStreamEnvelope(
        id=f"resource:{session_id}:{resource.id}",
        revision=_resource_revision(resource),
        emitted_at=emitted_at,
        event=ResourceUpdatedStreamEvent(resource=resource),
    )


def _subagent_updated_envelope(
    subagent: SubagentSummary, emitted_at: str
) -> TimelineStreamEnvelope:
    return TimelineStreamEnvelope(
        id=f"subagent:{subagent.parent_session_id}:{subagent.subagent_id}",
        revision=subagent.last_seq or subagent.first_seq or subagent.parent_seq or 0,
        emitted_at=emitted_at,
        event=SubagentUpdatedStreamEvent(subagent=subagent),
    )


def _session_updated_envelope(
    session: SessionRow, header: SessionHeader, emitted_at: str
) -> TimelineStreamEnvelope:
    return TimelineStreamEnvelope(
        id=f"session:{session.session_id}",
        revision=_session_revision(session),
        emitted_at=emitted_at,
        event=SessionUpdatedStreamEvent(session=header),
    )


def _resources_for_item(
    item: TimelineItemType, resources: dict[str, ResourceSummaryType]
) -> dict[str, ResourceSummaryType]:
    resource_refs = getattr(item, "resource_refs", ())
    return {
        ref.resource_id: resources[ref.resource_id]
        for ref in resource_refs
        if ref.resource_id in resources
    }


def _resource_revision(resource: ResourceSummaryType) -> int:
    source = getattr(resource, "source", None)
    if not isinstance(source, SourceRef):
        return 0
    return source.seq


def _session_revision(session: SessionRow) -> int:
    revised_at = session.updated_at or session.created_at or session.started_at
    return int(revised_at.timestamp() * 1000)


def _emitted_at() -> str:
    return datetime.now(UTC).isoformat()
