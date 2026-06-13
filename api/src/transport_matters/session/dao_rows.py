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


def strip_decoded_nuls(value: Any) -> Any:
    # Any: provider JSON can carry arbitrary nested scalar shapes at this boundary.
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {
            key.replace("\x00", "") if isinstance(key, str) else key: strip_decoded_nuls(nested)
            for key, nested in value.items()
        }
    if isinstance(value, list):
        return [strip_decoded_nuls(nested) for nested in value]
    if isinstance(value, tuple):
        return tuple(strip_decoded_nuls(nested) for nested in value)
    return value


def jsonb(value: dict[str, Any] | None) -> Jsonb | None:
    # Any: provider and IR JSON are intentionally opaque at this DAO boundary.
    return None if value is None else Jsonb(strip_decoded_nuls(value))


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
    data = {
        key: strip_decoded_nuls(value)
        for key, value in session.model_dump(
            mode="python", exclude={"created_at", "updated_at"}
        ).items()
    }
    data["source_descriptor"] = jsonb(data["source_descriptor"])
    return data


def event_params(event: EventRow) -> dict[str, Any]:
    # Any: psycopg parameter maps accept scalars plus Jsonb wrappers.
    data = {
        key: strip_decoded_nuls(value)
        for key, value in event.model_dump(
            mode="python", exclude={"artifacts", "created_at"}
        ).items()
    }
    data["raw"] = Jsonb(data["raw"])
    data["ir"] = jsonb(data["ir"])
    return data
