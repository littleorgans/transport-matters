"""Pure-SQL read surface over tier-2 (§8.2-8.6). No writes — safe against a live writer.

Every function reads through a connection the caller opened read-only (``query_only = ON``,
§8.1); under WAL these never block the §6 writer. Search is two-phase (§8.2): ``search_blocks``
returns metadata + snippet + bm25 rank, ``get_block_bodies`` fetches bodies for chosen ids.
The occurrence view unions both edge tables; the transcript side is empty until slice 4, so
search/timeline/pivot/diff return wire-only results gracefully today.
"""

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any  # Any: sqlite3 param/row values are dynamically typed

from transport_matters.index.models import (
    BlockBody,
    BlockHit,
    Correspondence,
    RawRef,
    SearchFilters,
    SessionDiff,
    SessionFilters,
    SessionRow,
    TimelineBlock,
    TimelineEntry,
)
from transport_matters.storage.disk_layout import DiskStorageLayout

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from typing import Literal

# Unified occurrence view over BOTH edge tables (§8.2). The transcript side is empty until
# slice 4 — UNION ALL returns wire rows + zero transcript rows, no special-casing needed.
_OCCURRENCE_VIEW = """(
  SELECT 'wire' AS stream, eb.block_id, eb.exchange_id AS entity_id, eb.role, eb.section,
         we.session_id, we.ts, we.run_id, we.provider, NULL AS cli, 0 AS is_sidechain
  FROM exchange_block eb JOIN wire_exchange we ON we.exchange_id = eb.exchange_id
  UNION ALL
  SELECT 'transcript', tb.block_id, tb.turn_id, tb.role, NULL,
         tt.session_id, tt.ts, tt.run_id, tt.provider, tt.cli, tt.is_sidechain
  FROM turn_block tb JOIN transcript_turn tt ON tt.turn_id = tb.turn_id
)"""

# All filters optional + AND-combined (§8.2). NULL bind = filter disabled.
_SEARCH_FILTERS = """
  AND (:kind      IS NULL OR b.kind       = :kind)
  AND (:stream    IS NULL OR e.stream     = :stream)
  AND (:provider  IS NULL OR e.provider   = :provider)
  AND (:cli       IS NULL OR e.cli        = :cli)
  AND (:role      IS NULL OR e.role       = :role)
  AND (:section   IS NULL OR e.section    = :section)
  AND (:session   IS NULL OR e.session_id = :session)
  AND (:run       IS NULL OR e.run_id     = :run)
  AND (:since     IS NULL OR e.ts        >= :since)
  AND (:until     IS NULL OR e.ts        <= :until)
  AND (:sidechain IS NULL OR e.is_sidechain = :sidechain)
"""

_SEARCH_OCCURRENCE_SQL = f"""
SELECT b.id, b.hash, b.kind, b.n_tokens,
       snippet(block_fts, 0, '[', ']', '...', 12) AS snippet,
       bm25(block_fts)                          AS rank,
       e.stream, e.entity_id, e.role, e.section, e.session_id, e.ts, e.run_id, e.provider
FROM block_fts
JOIN block b ON b.id = block_fts.rowid
JOIN {_OCCURRENCE_VIEW} e ON e.block_id = b.id
WHERE block_fts MATCH :q{_SEARCH_FILTERS}
ORDER BY rank
LIMIT :limit OFFSET :offset
"""

# Block-centric (dedup) view. bm25/snippet are FTS5 aux functions that cannot run under
# GROUP BY, and SQLite would flatten a plain subquery back into the aggregate. A MATERIALIZED
# CTE forces the FTS computation to complete first, so the outer aggregates plain columns.
_SEARCH_BLOCK_SQL = f"""
WITH hits AS MATERIALIZED (
  SELECT b.id AS id, b.hash AS hash, b.kind AS kind, b.n_tokens AS n_tokens,
         snippet(block_fts, 0, '[', ']', '...', 12) AS snippet,
         bm25(block_fts) AS rank,
         e.session_id AS session_id
  FROM block_fts
  JOIN block b ON b.id = block_fts.rowid
  JOIN {_OCCURRENCE_VIEW} e ON e.block_id = b.id
  WHERE block_fts MATCH :q{_SEARCH_FILTERS}
)
SELECT id, hash, kind, n_tokens, snippet, MIN(rank) AS rank,
       COUNT(*) AS occurrences, GROUP_CONCAT(DISTINCT session_id) AS sessions
FROM hits
GROUP BY id
ORDER BY rank
LIMIT :limit OFFSET :offset
"""

_PIVOT_SQL = """
SELECT eb.exchange_id, tb.turn_id, COUNT(*) AS shared_blocks
FROM exchange_block eb
JOIN turn_block tb       ON tb.block_id   = eb.block_id
JOIN wire_exchange   we  ON we.exchange_id = eb.exchange_id AND we.session_id = :session
JOIN transcript_turn tt  ON tt.turn_id     = tb.turn_id     AND tt.session_id = :session
GROUP BY eb.exchange_id, tb.turn_id
ORDER BY shared_blocks DESC
"""

_DIFF_SQL = """
WITH wire AS (SELECT DISTINCT eb.block_id FROM exchange_block eb
              JOIN wire_exchange we ON we.exchange_id = eb.exchange_id WHERE we.session_id = :s),
     tx   AS (SELECT DISTINCT tb.block_id FROM turn_block tb
              JOIN transcript_turn tt ON tt.turn_id = tb.turn_id WHERE tt.session_id = :s)
SELECT 'wire_only' AS bucket, block_id FROM wire WHERE block_id NOT IN (SELECT block_id FROM tx)
UNION ALL
SELECT 'transcript_only', block_id FROM tx WHERE block_id NOT IN (SELECT block_id FROM wire)
UNION ALL
SELECT 'shared', block_id FROM wire WHERE block_id IN (SELECT block_id FROM tx)
"""


def search_blocks(
    conn: sqlite3.Connection,
    q: str,
    *,
    filters: SearchFilters,
    mode: Literal["occurrence", "block"] = "occurrence",
    limit: int = 50,
    offset: int = 0,
) -> list[BlockHit]:
    """Phase 1: FTS5 hits (metadata + snippet + bm25 rank), filtered + ordered (§8.2)."""
    params: dict[str, Any] = {
        "q": q,
        "kind": filters.kind,
        "stream": filters.stream,
        "provider": filters.provider,
        "cli": filters.cli,
        "role": filters.role,
        "section": filters.section,
        "session": filters.session_id,
        "run": filters.run_id,
        "since": filters.since,
        "until": filters.until,
        "sidechain": filters.is_sidechain,
        "limit": limit,
        "offset": offset,
    }
    if mode == "block":
        return [
            BlockHit(
                id=r["id"],
                hash=r["hash"],
                kind=r["kind"],
                n_tokens=r["n_tokens"],
                snippet=r["snippet"],
                rank=r["rank"],
                occurrences=r["occurrences"],
                sessions=r["sessions"],
            )
            for r in _rows(conn, _SEARCH_BLOCK_SQL, params)
        ]
    return [
        BlockHit(
            id=r["id"],
            hash=r["hash"],
            kind=r["kind"],
            n_tokens=r["n_tokens"],
            snippet=r["snippet"],
            rank=r["rank"],
            stream=r["stream"],
            entity_id=r["entity_id"],
            role=r["role"],
            section=r["section"],
            session_id=r["session_id"],
            ts=r["ts"],
            run_id=r["run_id"],
            provider=r["provider"],
        )
        for r in _rows(conn, _SEARCH_OCCURRENCE_SQL, params)
    ]


def get_block_bodies(conn: sqlite3.Connection, ids: list[int]) -> list[BlockBody]:
    """Phase 2: full bodies for the chosen block ids (§8.2)."""
    if not ids:
        return []
    placeholders = ", ".join("?" * len(ids))
    sql = (
        f"SELECT id, hash, kind, text, identity_canonical, n_tokens FROM block "
        f"WHERE id IN ({placeholders})"
    )
    return [
        BlockBody(
            id=r["id"],
            hash=r["hash"],
            kind=r["kind"],
            text=r["text"],
            identity_canonical=r["identity_canonical"],
            n_tokens=r["n_tokens"],
        )
        for r in _rows(conn, sql, ids)
    ]


def list_sessions(conn: sqlite3.Connection, *, filters: SessionFilters) -> list[SessionRow]:
    """List sessions, optionally filtered by workspace / run / provider / cli (§8.6)."""
    params: dict[str, Any] = {
        "workspace_hash": filters.workspace_hash,
        "run_id": filters.run_id,
        "provider": filters.provider,
        "cli": filters.cli,
    }
    sql = """
        SELECT session_id, provider, cli, run_id, cwd, workspace_slug, workspace_hash,
               native_session_id, minted, source_descriptor, started_at
        FROM session
        WHERE (:workspace_hash IS NULL OR workspace_hash = :workspace_hash)
          AND (:run_id   IS NULL OR run_id   = :run_id)
          AND (:provider IS NULL OR provider = :provider)
          AND (:cli      IS NULL OR cli      = :cli)
        ORDER BY started_at
    """
    return [
        SessionRow(
            session_id=r["session_id"],
            provider=r["provider"],
            cli=r["cli"],
            run_id=r["run_id"],
            cwd=r["cwd"],
            workspace_slug=r["workspace_slug"],
            workspace_hash=r["workspace_hash"],
            native_session_id=r["native_session_id"],
            minted=r["minted"],
            source_descriptor=r["source_descriptor"],
            started_at=r["started_at"],
        )
        for r in _rows(conn, sql, params)
    ]


def session_timeline(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    stream: Literal["wire", "transcript"],
    with_bodies: bool = False,
    seq_from: int | None = None,
    seq_to: int | None = None,
) -> list[TimelineEntry]:
    """Reconstruct one stream's ordered conversation for a session (§8.3)."""
    if stream == "wire":
        entities = _rows(
            conn,
            "SELECT exchange_id, seq, ts FROM wire_exchange WHERE session_id = :s "
            "AND (:lo IS NULL OR seq >= :lo) AND (:hi IS NULL OR seq <= :hi) ORDER BY seq",
            {"s": session_id, "lo": seq_from, "hi": seq_to},
        )
        return [
            TimelineEntry(
                stream="wire",
                entity_id=r["exchange_id"],
                seq=r["seq"],
                ts=r["ts"],
                blocks=_edge_blocks(
                    conn, "exchange_block", "exchange_id", r["exchange_id"], with_bodies
                ),
            )
            for r in entities
        ]
    entities = _rows(
        conn,
        "SELECT turn_id, seq, ts, parent_id, is_sidechain FROM transcript_turn "
        "WHERE session_id = :s AND (:lo IS NULL OR seq >= :lo) AND (:hi IS NULL OR seq <= :hi) "
        "ORDER BY seq",
        {"s": session_id, "lo": seq_from, "hi": seq_to},
    )
    return [
        TimelineEntry(
            stream="transcript",
            entity_id=r["turn_id"],
            seq=r["seq"],
            ts=r["ts"],
            parent_id=r["parent_id"],
            is_sidechain=r["is_sidechain"],
            blocks=_edge_blocks(conn, "turn_block", "turn_id", r["turn_id"], with_bodies),
        )
        for r in entities
    ]


def session_pivot(conn: sqlite3.Connection, session_id: str) -> list[Correspondence]:
    """Strongest wire-exchange ↔ transcript-turn correspondences by shared blocks (§8.4)."""
    return [
        Correspondence(
            exchange_id=r["exchange_id"], turn_id=r["turn_id"], shared_blocks=r["shared_blocks"]
        )
        for r in _rows(conn, _PIVOT_SQL, {"session": session_id})
    ]


def session_diff(conn: sqlite3.Connection, session_id: str) -> SessionDiff:
    """The §1.1 block-set DIFF: wire_only / transcript_only / shared block ids (§8.4)."""
    buckets: dict[str, list[int]] = {"wire_only": [], "transcript_only": [], "shared": []}
    for r in _rows(conn, _DIFF_SQL, {"s": session_id}):
        buckets[r["bucket"]].append(r["block_id"])
    return SessionDiff(
        wire_only=buckets["wire_only"],
        transcript_only=buckets["transcript_only"],
        shared=buckets["shared"],
    )


def exchange_raw_ref(conn: sqlite3.Connection, exchange_id: str) -> RawRef:
    """Resolve a wire exchange's tier-1 raw-bytes pointer (§8.5). Raises KeyError if unknown."""
    rows = _rows(
        conn, "SELECT raw_dir FROM wire_exchange WHERE exchange_id = :id", {"id": exchange_id}
    )
    if not rows:
        raise KeyError(exchange_id)
    raw_dir = rows[0]["raw_dir"]
    paths = DiskStorageLayout().artifact_paths(Path(raw_dir))
    return RawRef(
        exchange_id=exchange_id,
        raw_dir=raw_dir,
        request_raw=str(paths.request_raw),
        response_raw=str(paths.response_raw),
    )


def _edge_blocks(
    conn: sqlite3.Connection, edge_table: str, key_column: str, entity_id: str, with_bodies: bool
) -> list[TimelineBlock]:
    # edge_table / key_column are internal literals (two fixed call sites), never user input.
    section_col = "e.section" if edge_table == "exchange_block" else "NULL AS section"
    body = ", b.text, b.identity_canonical" if with_bodies else ""
    join = "JOIN block b ON b.id = e.block_id" if with_bodies else ""
    sql = (
        f"SELECT e.pos, e.block_id, e.role, {section_col}{body} "
        f"FROM {edge_table} e {join} WHERE e.{key_column} = :id ORDER BY e.pos"
    )
    return [
        TimelineBlock(
            pos=r["pos"],
            block_id=r["block_id"],
            role=r["role"],
            section=r["section"],
            text=r["text"] if with_bodies else None,
            identity_canonical=r["identity_canonical"] if with_bodies else None,
        )
        for r in _rows(conn, sql, {"id": entity_id})
    ]


def _rows(
    conn: sqlite3.Connection, sql: str, params: Mapping[str, Any] | Sequence[Any]
) -> list[sqlite3.Row]:
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    cursor.execute(sql, params)
    return cursor.fetchall()
