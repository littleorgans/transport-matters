from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.types.json import Jsonb

from transport_matters.session.artifacts import artifact_hash
from transport_matters.session.dao_rows import (
    artifact_row,
    child_session_row,
    dead_letter_params,
    event_artifact_row,
    event_params,
    event_read_row,
    event_row,
    events_with_artifacts,
    jsonb,
    one_session,
    session_params,
    strip_decoded_nuls,
)
from transport_matters.session.dao_statements import (
    COUNT_DEAD_LETTERS_BY_RUN_SQL,
    COUNT_DEAD_LETTERS_BY_SESSION_SQL,
    GET_ARTIFACT_SQL,
    GET_EVENT_ARTIFACTS_FOR_SEQS_SQL,
    GET_EVENTS_FOR_OWNER_SQL,
    GET_EVENTS_SQL,
    GET_EVENTS_WITH_RAW_FOR_OWNER_SQL,
    GET_LATEST_TURN_BEFORE_WITH_RAW_FOR_OWNER_SQL,
    GET_SESSION_FOR_OWNER_SQL,
    GET_SESSION_SQL,
    INSERT_DEAD_LETTER_SQL,
    INSERT_EVENT_SQL,
    IR_SEARCH_SQL,
    LINK_ARTIFACT_SQL,
    LIST_CHILD_SESSIONS_FOR_OWNER_SQL,
    LIST_SESSIONS_SQL,
    TEXT_SEARCH_SQL,
    UPSERT_ARTIFACT_SQL,
    UPSERT_SESSION_SQL,
)
from transport_matters.session.models import (
    ArtifactRow,
    ChildSessionRow,
    EventArtifactRow,
    EventReadRow,
    EventRow,
    SessionRow,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from psycopg import AsyncConnection
    from psycopg.rows import DictRow

    from transport_matters.session.models import DeadLetterWrite


class AsyncSessionDao:
    def __init__(self, conn: AsyncConnection[DictRow]) -> None:
        self._conn = conn

    async def upsert_session(self, session: SessionRow) -> SessionRow:
        cursor = await self._conn.execute(UPSERT_SESSION_SQL, session_params(session))
        row = await cursor.fetchone()
        assert row is not None
        return SessionRow.model_validate(dict(row))

    async def get_session(self, session_id: str) -> SessionRow | None:
        cursor = await self._conn.execute(GET_SESSION_SQL, {"session_id": session_id})
        row = await cursor.fetchone()
        return one_session(row)

    async def get_session_for_owner(self, session_id: str, *, owner: str) -> SessionRow | None:
        cursor = await self._conn.execute(
            GET_SESSION_FOR_OWNER_SQL,
            {"session_id": session_id, "owner": owner},
        )
        row = await cursor.fetchone()
        return one_session(row)

    async def list_sessions(
        self,
        *,
        owner: str,
        workspace_hash: str | None = None,
        provider: str | None = None,
        cli: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SessionRow]:
        cursor = await self._conn.execute(
            LIST_SESSIONS_SQL,
            {
                "owner": owner,
                "workspace_hash": workspace_hash,
                "provider": provider,
                "cli": cli,
                "status": status,
                "limit": limit,
                "offset": offset,
            },
        )
        rows = await cursor.fetchall()
        return [SessionRow.model_validate(dict(row)) for row in rows]

    async def list_child_sessions_for_owner(
        self, parent_session_id: str, *, owner: str
    ) -> list[ChildSessionRow]:
        cursor = await self._conn.execute(
            LIST_CHILD_SESSIONS_FOR_OWNER_SQL,
            {"parent_session_id": parent_session_id, "owner": owner},
        )
        rows = await cursor.fetchall()
        return [child_session_row(row) for row in rows]

    async def insert_event(self, event: EventRow) -> EventRow:
        cursor = await self._conn.execute(INSERT_EVENT_SQL, event_params(event))
        row = await cursor.fetchone()
        assert row is not None
        return event_row(row)

    async def insert_dead_letter(self, letter: DeadLetterWrite) -> None:
        await self._conn.execute(INSERT_DEAD_LETTER_SQL, dead_letter_params(letter))

    async def count_dead_letters_by_run(self, run_ids: Sequence[str]) -> dict[str, int]:
        if not run_ids:
            return {}
        cursor = await self._conn.execute(COUNT_DEAD_LETTERS_BY_RUN_SQL, {"run_ids": list(run_ids)})
        rows = await cursor.fetchall()
        return {str(row["run_id"]): int(row["dead_letter_count"]) for row in rows}

    async def count_dead_letters_by_session(self, session_ids: Sequence[str]) -> dict[str, int]:
        if not session_ids:
            return {}
        cursor = await self._conn.execute(
            COUNT_DEAD_LETTERS_BY_SESSION_SQL, {"session_ids": list(session_ids)}
        )
        rows = await cursor.fetchall()
        return {str(row["session_id"]): int(row["dead_letter_count"]) for row in rows}

    async def get_events(
        self, session_id: str, *, from_seq: int | None = None, to_seq: int | None = None
    ) -> list[EventRow]:
        cursor = await self._conn.execute(
            GET_EVENTS_SQL,
            {"session_id": session_id, "from_seq": from_seq, "to_seq": to_seq},
        )
        rows = await cursor.fetchall()
        return [event_row(row) for row in rows]

    async def get_events_for_owner(
        self,
        session_id: str,
        *,
        owner: str,
        from_seq: int | None = None,
        to_seq: int | None = None,
        limit: int = 500,
    ) -> list[EventReadRow]:
        cursor = await self._conn.execute(
            GET_EVENTS_FOR_OWNER_SQL,
            {
                "session_id": session_id,
                "owner": owner,
                "from_seq": from_seq,
                "to_seq": to_seq,
                "limit": limit,
            },
        )
        rows = await cursor.fetchall()
        return [event_read_row(row) for row in rows]

    async def get_events_with_raw_for_owner(
        self,
        session_id: str,
        *,
        owner: str,
        from_seq: int | None = None,
        to_seq: int | None = None,
        limit: int = 500,
    ) -> list[EventRow]:
        cursor = await self._conn.execute(
            GET_EVENTS_WITH_RAW_FOR_OWNER_SQL,
            {
                "session_id": session_id,
                "owner": owner,
                "from_seq": from_seq,
                "to_seq": to_seq,
                "limit": limit,
            },
        )
        rows = await cursor.fetchall()
        events = [event_row(row) for row in rows]
        if not events:
            return events
        artifact_cursor = await self._conn.execute(
            GET_EVENT_ARTIFACTS_FOR_SEQS_SQL,
            {"session_id": session_id, "seqs": [event.seq for event in events]},
        )
        artifact_rows = await artifact_cursor.fetchall()
        return events_with_artifacts(events, [event_artifact_row(row) for row in artifact_rows])

    async def get_latest_turn_before_with_raw_for_owner(
        self, session_id: str, *, owner: str, before_seq: int
    ) -> EventRow | None:
        cursor = await self._conn.execute(
            GET_LATEST_TURN_BEFORE_WITH_RAW_FOR_OWNER_SQL,
            {"session_id": session_id, "owner": owner, "before_seq": before_seq},
        )
        row = await cursor.fetchone()
        return event_row(row) if row is not None else None

    async def events_matching_ir(
        self, filter_: dict[str, Any], *, limit: int = 50
    ) -> list[EventRow]:
        # Any: filter JSON is a caller supplied JSONB containment expression.
        cursor = await self._conn.execute(
            IR_SEARCH_SQL,
            {"filter": Jsonb(filter_), "limit": limit},
        )
        rows = await cursor.fetchall()
        return [event_row(row) for row in rows]

    async def search_event_text(self, query: str, *, limit: int = 50) -> list[EventRow]:
        cursor = await self._conn.execute(TEXT_SEARCH_SQL, {"query": query, "limit": limit})
        rows = await cursor.fetchall()
        return [event_row(row) for row in rows]

    async def upsert_artifact(self, data: bytes, *, media_type: str | None = None) -> ArtifactRow:
        hash_ = artifact_hash(data)
        cursor = await self._conn.execute(
            UPSERT_ARTIFACT_SQL,
            {
                "hash": hash_,
                "media_type": strip_decoded_nuls(media_type),
                "size_bytes": len(data),
                "bytes": data,
            },
        )
        row = await cursor.fetchone()
        if row is not None:
            return artifact_row(row)
        existing = await self.get_artifact(hash_)
        assert existing is not None
        return existing

    async def get_artifact(self, hash_: str) -> ArtifactRow | None:
        cursor = await self._conn.execute(GET_ARTIFACT_SQL, {"hash": hash_})
        row = await cursor.fetchone()
        return None if row is None else artifact_row(row)

    async def link_artifact(
        self, session_id: str, seq: int, artifact_hash_: str, ref: dict[str, Any] | None = None
    ) -> EventArtifactRow:
        # Any: ref JSON is a provider scoped artifact pointer.
        cursor = await self._conn.execute(
            LINK_ARTIFACT_SQL,
            {
                "session_id": session_id,
                "seq": seq,
                "artifact_hash": artifact_hash_,
                "ref": jsonb(ref),
            },
        )
        row = await cursor.fetchone()
        assert row is not None
        return event_artifact_row(row)
