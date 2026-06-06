from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.types.json import Jsonb

from transport_matters.session.artifacts import artifact_hash
from transport_matters.session.models import (
    ArtifactRow,
    EventArtifactRow,
    EventReadRow,
    EventRow,
    SessionRow,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from psycopg import AsyncConnection, Connection
    from psycopg.rows import DictRow

_SESSION_COLUMNS = """
    session_id, provider, cli, run_id, cwd, workspace_slug, workspace_hash,
    native_session_id, minted, source_descriptor, home_dir, owner, status, title,
    parent_session_id, forked_at_seq, started_at, created_at, updated_at
"""
_EVENT_COLUMN_NAMES = (
    "session_id",
    "seq",
    "kind",
    "native_turn_id",
    "parent_native_id",
    "parent_seq",
    "run_id",
    "provider",
    "cli",
    "role",
    "is_sidechain",
    "ts",
    "model",
    "raw",
    "ir",
    "source_path",
    "source_line",
    "search_text",
    "created_at",
)
_EVENT_READ_COLUMN_NAMES = tuple(name for name in _EVENT_COLUMN_NAMES if name != "raw")
_EVENT_COLUMNS = ", ".join(_EVENT_COLUMN_NAMES)
_EVENT_READ_COLUMNS = ", ".join(f"e.{name}" for name in _EVENT_READ_COLUMN_NAMES)
_ARTIFACT_COLUMNS = "hash, media_type, size_bytes, bytes, created_at"

_UPSERT_SESSION_SQL = f"""
INSERT INTO "session" (
    session_id, provider, cli, run_id, cwd, workspace_slug, workspace_hash,
    native_session_id, minted, source_descriptor, home_dir, owner, status, title,
    parent_session_id, forked_at_seq, started_at
) VALUES (
    %(session_id)s, %(provider)s, %(cli)s, %(run_id)s, %(cwd)s, %(workspace_slug)s,
    %(workspace_hash)s, %(native_session_id)s, %(minted)s, %(source_descriptor)s,
    %(home_dir)s, %(owner)s, %(status)s, %(title)s, %(parent_session_id)s,
    %(forked_at_seq)s, %(started_at)s
)
ON CONFLICT (session_id) DO UPDATE SET
    provider = EXCLUDED.provider,
    cli = COALESCE("session".cli, EXCLUDED.cli),
    run_id = EXCLUDED.run_id,
    cwd = COALESCE(NULLIF("session".cwd, ''), EXCLUDED.cwd),
    workspace_slug = EXCLUDED.workspace_slug,
    workspace_hash = EXCLUDED.workspace_hash,
    native_session_id = COALESCE("session".native_session_id, EXCLUDED.native_session_id),
    minted = "session".minted OR EXCLUDED.minted,
    source_descriptor = COALESCE("session".source_descriptor, EXCLUDED.source_descriptor),
    home_dir = COALESCE("session".home_dir, EXCLUDED.home_dir),
    owner = EXCLUDED.owner,
    status = EXCLUDED.status,
    title = COALESCE(EXCLUDED.title, "session".title),
    parent_session_id = COALESCE("session".parent_session_id, EXCLUDED.parent_session_id),
    forked_at_seq = COALESCE("session".forked_at_seq, EXCLUDED.forked_at_seq),
    updated_at = now()
RETURNING {_SESSION_COLUMNS}
"""

_GET_SESSION_SQL = f'SELECT {_SESSION_COLUMNS} FROM "session" WHERE session_id = %(session_id)s'
_GET_SESSION_FOR_OWNER_SQL = f"""
SELECT {_SESSION_COLUMNS}
FROM "session"
WHERE session_id = %(session_id)s
  AND owner = %(owner)s
"""
_LIST_SESSIONS_SQL = f"""
SELECT {_SESSION_COLUMNS}
FROM "session"
WHERE owner = %(owner)s
  AND (%(workspace_hash)s::text IS NULL OR workspace_hash = %(workspace_hash)s)
  AND (%(provider)s::text IS NULL OR provider = %(provider)s)
  AND (%(cli)s::text IS NULL OR cli = %(cli)s)
  AND (%(status)s::text IS NULL OR status = %(status)s)
ORDER BY started_at DESC, session_id
LIMIT %(limit)s
OFFSET %(offset)s
"""

_INSERT_EVENT_SQL = f"""
INSERT INTO "event" (
    session_id, seq, kind, native_turn_id, parent_native_id, parent_seq, run_id,
    provider, cli, role, is_sidechain, ts, model, raw, ir, source_path,
    source_line, search_text
) VALUES (
    %(session_id)s, %(seq)s, %(kind)s, %(native_turn_id)s, %(parent_native_id)s,
    %(parent_seq)s, %(run_id)s, %(provider)s, %(cli)s, %(role)s, %(is_sidechain)s,
    %(ts)s, %(model)s, %(raw)s, %(ir)s, %(source_path)s, %(source_line)s,
    %(search_text)s
)
ON CONFLICT (session_id, seq) DO UPDATE SET
    kind = EXCLUDED.kind,
    native_turn_id = EXCLUDED.native_turn_id,
    parent_native_id = EXCLUDED.parent_native_id,
    parent_seq = EXCLUDED.parent_seq,
    run_id = EXCLUDED.run_id,
    provider = EXCLUDED.provider,
    cli = EXCLUDED.cli,
    role = EXCLUDED.role,
    is_sidechain = EXCLUDED.is_sidechain,
    ts = EXCLUDED.ts,
    model = EXCLUDED.model,
    raw = EXCLUDED.raw,
    ir = EXCLUDED.ir,
    source_path = EXCLUDED.source_path,
    source_line = EXCLUDED.source_line,
    search_text = EXCLUDED.search_text
RETURNING {_EVENT_COLUMNS}
"""

_GET_EVENTS_SQL = f"""
SELECT {_EVENT_COLUMNS}
FROM "event"
WHERE session_id = %(session_id)s
  AND (%(from_seq)s::integer IS NULL OR seq >= %(from_seq)s::integer)
  AND (%(to_seq)s::integer IS NULL OR seq <= %(to_seq)s::integer)
ORDER BY seq
"""
_GET_EVENTS_FOR_OWNER_SQL = f"""
SELECT {_EVENT_READ_COLUMNS}
FROM "event" AS e
JOIN "session" AS s ON s.session_id = e.session_id
WHERE e.session_id = %(session_id)s
  AND s.owner = %(owner)s
  AND (%(from_seq)s::integer IS NULL OR e.seq >= %(from_seq)s::integer)
  AND (%(to_seq)s::integer IS NULL OR e.seq <= %(to_seq)s::integer)
ORDER BY e.seq
LIMIT %(limit)s
"""

_IR_SEARCH_SQL = f"""
SELECT {_EVENT_COLUMNS}
FROM "event"
WHERE kind = 'turn'
  AND ir @> %(filter)s
ORDER BY session_id, seq
LIMIT %(limit)s
"""

_TEXT_SEARCH_SQL = f"""
SELECT {_EVENT_COLUMNS}
FROM "event"
WHERE kind = 'turn'
  AND content_tsv @@ websearch_to_tsquery('english', %(query)s)
ORDER BY ts_rank_cd(content_tsv, websearch_to_tsquery('english', %(query)s)) DESC, session_id, seq
LIMIT %(limit)s
"""

_UPSERT_ARTIFACT_SQL = f"""
INSERT INTO artifact (hash, media_type, size_bytes, bytes)
VALUES (%(hash)s, %(media_type)s, %(size_bytes)s, %(bytes)s)
ON CONFLICT (hash) DO NOTHING
RETURNING {_ARTIFACT_COLUMNS}
"""

_GET_ARTIFACT_SQL = f"SELECT {_ARTIFACT_COLUMNS} FROM artifact WHERE hash = %(hash)s"

_LINK_ARTIFACT_SQL = """
INSERT INTO event_artifact (session_id, seq, artifact_hash, ref)
VALUES (%(session_id)s, %(seq)s, %(artifact_hash)s, %(ref)s)
ON CONFLICT (session_id, seq, artifact_hash) DO UPDATE SET ref = EXCLUDED.ref
RETURNING session_id, seq, artifact_hash, ref
"""


def _jsonb(value: dict[str, Any] | None) -> Jsonb | None:
    # Any: provider and IR JSON are intentionally opaque at this DAO boundary.
    return None if value is None else Jsonb(value)


def _one(row: Mapping[str, Any] | None, model: type[SessionRow]) -> SessionRow | None:
    # Any: psycopg DictRow stores database values with driver supplied types.
    return None if row is None else model.model_validate(dict(row))


def _event(row: Mapping[str, Any]) -> EventRow:
    # Any: psycopg DictRow stores database values with driver supplied types.
    return EventRow.model_validate(dict(row))


def _event_read(row: Mapping[str, Any]) -> EventReadRow:
    # Any: psycopg DictRow stores database values with driver supplied types.
    return EventReadRow.model_validate(dict(row))


def _artifact(row: Mapping[str, Any]) -> ArtifactRow:
    # Any: psycopg DictRow stores database values with driver supplied types.
    return ArtifactRow.model_validate(dict(row))


def _event_artifact(row: Mapping[str, Any]) -> EventArtifactRow:
    # Any: psycopg DictRow stores database values with driver supplied types.
    return EventArtifactRow.model_validate(dict(row))


def _session_params(session: SessionRow) -> dict[str, Any]:
    # Any: psycopg parameter maps accept scalars plus Jsonb wrappers.
    data = session.model_dump(mode="python", exclude={"created_at", "updated_at"})
    data["source_descriptor"] = _jsonb(session.source_descriptor)
    return data


def _event_params(event: EventRow) -> dict[str, Any]:
    # Any: psycopg parameter maps accept scalars plus Jsonb wrappers.
    data = event.model_dump(mode="python", exclude={"created_at"})
    data["raw"] = Jsonb(event.raw)
    data["ir"] = _jsonb(event.ir)
    return data


class SessionDao:
    def __init__(self, conn: Connection[DictRow]) -> None:
        self._conn = conn

    def upsert_session(self, session: SessionRow) -> SessionRow:
        row = self._conn.execute(_UPSERT_SESSION_SQL, _session_params(session)).fetchone()
        assert row is not None
        return SessionRow.model_validate(dict(row))

    def get_session(self, session_id: str) -> SessionRow | None:
        row = self._conn.execute(_GET_SESSION_SQL, {"session_id": session_id}).fetchone()
        return _one(row, SessionRow)

    def get_session_for_owner(self, session_id: str, *, owner: str) -> SessionRow | None:
        row = self._conn.execute(
            _GET_SESSION_FOR_OWNER_SQL,
            {"session_id": session_id, "owner": owner},
        ).fetchone()
        return _one(row, SessionRow)

    def list_sessions(
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
        rows = self._conn.execute(
            _LIST_SESSIONS_SQL,
            {
                "owner": owner,
                "workspace_hash": workspace_hash,
                "provider": provider,
                "cli": cli,
                "status": status,
                "limit": limit,
                "offset": offset,
            },
        ).fetchall()
        return [SessionRow.model_validate(dict(row)) for row in rows]

    def insert_event(self, event: EventRow) -> EventRow:
        row = self._conn.execute(_INSERT_EVENT_SQL, _event_params(event)).fetchone()
        assert row is not None
        return _event(row)

    def get_events(
        self, session_id: str, *, from_seq: int | None = None, to_seq: int | None = None
    ) -> list[EventRow]:
        rows = self._conn.execute(
            _GET_EVENTS_SQL,
            {"session_id": session_id, "from_seq": from_seq, "to_seq": to_seq},
        ).fetchall()
        return [_event(row) for row in rows]

    def get_events_for_owner(
        self,
        session_id: str,
        *,
        owner: str,
        from_seq: int | None = None,
        to_seq: int | None = None,
        limit: int = 500,
    ) -> list[EventReadRow]:
        rows = self._conn.execute(
            _GET_EVENTS_FOR_OWNER_SQL,
            {
                "session_id": session_id,
                "owner": owner,
                "from_seq": from_seq,
                "to_seq": to_seq,
                "limit": limit,
            },
        ).fetchall()
        return [_event_read(row) for row in rows]

    def events_matching_ir(self, filter_: dict[str, Any], *, limit: int = 50) -> list[EventRow]:
        # Any: filter JSON is a caller supplied JSONB containment expression.
        rows = self._conn.execute(
            _IR_SEARCH_SQL,
            {"filter": Jsonb(filter_), "limit": limit},
        ).fetchall()
        return [_event(row) for row in rows]

    def search_event_text(self, query: str, *, limit: int = 50) -> list[EventRow]:
        rows = self._conn.execute(_TEXT_SEARCH_SQL, {"query": query, "limit": limit}).fetchall()
        return [_event(row) for row in rows]

    def upsert_artifact(self, data: bytes, *, media_type: str | None = None) -> ArtifactRow:
        hash_ = artifact_hash(data)
        row = self._conn.execute(
            _UPSERT_ARTIFACT_SQL,
            {"hash": hash_, "media_type": media_type, "size_bytes": len(data), "bytes": data},
        ).fetchone()
        if row is not None:
            return _artifact(row)
        existing = self.get_artifact(hash_)
        assert existing is not None
        return existing

    def get_artifact(self, hash_: str) -> ArtifactRow | None:
        row = self._conn.execute(_GET_ARTIFACT_SQL, {"hash": hash_}).fetchone()
        return None if row is None else _artifact(row)

    def link_artifact(
        self, session_id: str, seq: int, artifact_hash_: str, ref: dict[str, Any] | None = None
    ) -> EventArtifactRow:
        # Any: ref JSON is a provider scoped artifact pointer.
        row = self._conn.execute(
            _LINK_ARTIFACT_SQL,
            {
                "session_id": session_id,
                "seq": seq,
                "artifact_hash": artifact_hash_,
                "ref": _jsonb(ref),
            },
        ).fetchone()
        assert row is not None
        return _event_artifact(row)


class AsyncSessionDao:
    def __init__(self, conn: AsyncConnection[DictRow]) -> None:
        self._conn = conn

    async def upsert_session(self, session: SessionRow) -> SessionRow:
        cursor = await self._conn.execute(_UPSERT_SESSION_SQL, _session_params(session))
        row = await cursor.fetchone()
        assert row is not None
        return SessionRow.model_validate(dict(row))

    async def get_session(self, session_id: str) -> SessionRow | None:
        cursor = await self._conn.execute(_GET_SESSION_SQL, {"session_id": session_id})
        row = await cursor.fetchone()
        return _one(row, SessionRow)

    async def get_session_for_owner(self, session_id: str, *, owner: str) -> SessionRow | None:
        cursor = await self._conn.execute(
            _GET_SESSION_FOR_OWNER_SQL,
            {"session_id": session_id, "owner": owner},
        )
        row = await cursor.fetchone()
        return _one(row, SessionRow)

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
            _LIST_SESSIONS_SQL,
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

    async def insert_event(self, event: EventRow) -> EventRow:
        cursor = await self._conn.execute(_INSERT_EVENT_SQL, _event_params(event))
        row = await cursor.fetchone()
        assert row is not None
        return _event(row)

    async def get_events(
        self, session_id: str, *, from_seq: int | None = None, to_seq: int | None = None
    ) -> list[EventRow]:
        cursor = await self._conn.execute(
            _GET_EVENTS_SQL,
            {"session_id": session_id, "from_seq": from_seq, "to_seq": to_seq},
        )
        rows = await cursor.fetchall()
        return [_event(row) for row in rows]

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
            _GET_EVENTS_FOR_OWNER_SQL,
            {
                "session_id": session_id,
                "owner": owner,
                "from_seq": from_seq,
                "to_seq": to_seq,
                "limit": limit,
            },
        )
        rows = await cursor.fetchall()
        return [_event_read(row) for row in rows]

    async def events_matching_ir(
        self, filter_: dict[str, Any], *, limit: int = 50
    ) -> list[EventRow]:
        # Any: filter JSON is a caller supplied JSONB containment expression.
        cursor = await self._conn.execute(
            _IR_SEARCH_SQL,
            {"filter": Jsonb(filter_), "limit": limit},
        )
        rows = await cursor.fetchall()
        return [_event(row) for row in rows]

    async def search_event_text(self, query: str, *, limit: int = 50) -> list[EventRow]:
        cursor = await self._conn.execute(_TEXT_SEARCH_SQL, {"query": query, "limit": limit})
        rows = await cursor.fetchall()
        return [_event(row) for row in rows]

    async def upsert_artifact(self, data: bytes, *, media_type: str | None = None) -> ArtifactRow:
        hash_ = artifact_hash(data)
        cursor = await self._conn.execute(
            _UPSERT_ARTIFACT_SQL,
            {"hash": hash_, "media_type": media_type, "size_bytes": len(data), "bytes": data},
        )
        row = await cursor.fetchone()
        if row is not None:
            return _artifact(row)
        existing = await self.get_artifact(hash_)
        assert existing is not None
        return existing

    async def get_artifact(self, hash_: str) -> ArtifactRow | None:
        cursor = await self._conn.execute(_GET_ARTIFACT_SQL, {"hash": hash_})
        row = await cursor.fetchone()
        return None if row is None else _artifact(row)

    async def link_artifact(
        self, session_id: str, seq: int, artifact_hash_: str, ref: dict[str, Any] | None = None
    ) -> EventArtifactRow:
        # Any: ref JSON is a provider scoped artifact pointer.
        cursor = await self._conn.execute(
            _LINK_ARTIFACT_SQL,
            {
                "session_id": session_id,
                "seq": seq,
                "artifact_hash": artifact_hash_,
                "ref": _jsonb(ref),
            },
        )
        row = await cursor.fetchone()
        assert row is not None
        return _event_artifact(row)
