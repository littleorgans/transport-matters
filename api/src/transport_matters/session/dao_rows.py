from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.types.json import Jsonb

from transport_matters.session.models import (
    ArtifactRow,
    ChildSessionRow,
    EventArtifactRow,
    EventReadRow,
    EventRow,
    SessionRow,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def jsonb(value: dict[str, Any] | None) -> Jsonb | None:
    # Any: provider and IR JSON are intentionally opaque at this DAO boundary.
    return None if value is None else Jsonb(value)


def one_session(row: Mapping[str, Any] | None) -> SessionRow | None:
    # Any: psycopg DictRow stores database values with driver supplied types.
    return None if row is None else SessionRow.model_validate(dict(row))


def child_session_row(row: Mapping[str, Any]) -> ChildSessionRow:
    # Any: psycopg DictRow stores database values with driver supplied types.
    return ChildSessionRow.model_validate(dict(row))


def event_row(row: Mapping[str, Any]) -> EventRow:
    # Any: psycopg DictRow stores database values with driver supplied types.
    return EventRow.model_validate(dict(row))


def event_read_row(row: Mapping[str, Any]) -> EventReadRow:
    # Any: psycopg DictRow stores database values with driver supplied types.
    return EventReadRow.model_validate(dict(row))


def artifact_row(row: Mapping[str, Any]) -> ArtifactRow:
    # Any: psycopg DictRow stores database values with driver supplied types.
    return ArtifactRow.model_validate(dict(row))


def event_artifact_row(row: Mapping[str, Any]) -> EventArtifactRow:
    # Any: psycopg DictRow stores database values with driver supplied types.
    return EventArtifactRow.model_validate(dict(row))


def events_with_artifacts(
    events: list[EventRow], artifacts: list[EventArtifactRow]
) -> list[EventRow]:
    artifacts_by_seq: dict[int, list[EventArtifactRow]] = {}
    for artifact in artifacts:
        artifacts_by_seq.setdefault(artifact.seq, []).append(artifact)
    return [
        event.model_copy(update={"artifacts": tuple(artifacts_by_seq.get(event.seq, ()))})
        for event in events
    ]


def session_params(session: SessionRow) -> dict[str, Any]:
    # Any: psycopg parameter maps accept scalars plus Jsonb wrappers.
    data = session.model_dump(mode="python", exclude={"created_at", "updated_at"})
    data["source_descriptor"] = jsonb(session.source_descriptor)
    return data


def event_params(event: EventRow) -> dict[str, Any]:
    # Any: psycopg parameter maps accept scalars plus Jsonb wrappers.
    data = event.model_dump(mode="python", exclude={"artifacts", "created_at"})
    data["raw"] = Jsonb(event.raw)
    data["ir"] = jsonb(event.ir)
    return data
