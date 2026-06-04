"""Tier-2 schema: the §3.2-3.6 DDL, the schema_meta version gate, and FTS rebuild.

Tier-2 is a pure rebuildable projection of tier-1, so there are no migrations: on a boot
mismatch the whole schema is dropped and rebuilt (§3.2). ``apply_schema`` is the single,
idempotent, self-healing entry point.
"""

from typing import TYPE_CHECKING

from transport_matters.index.sessions import SESSION_NS

if TYPE_CHECKING:
    import sqlite3

SCHEMA_VERSION = "1"
BLOCK_HASH_ALGO = "blake2b-256"
IDENTITY_CANONICAL_VERSION = "identity_canonical:v1"
ADAPTERS_VERSION = "1"

# Seeded into schema_meta on create. block_hash_algo is recorded for provenance but not
# gated (it is constant for the life of the algorithm); the rest are gated on boot.
_SCHEMA_META: dict[str, str] = {
    "schema_version": SCHEMA_VERSION,
    "block_hash_algo": BLOCK_HASH_ALGO,
    "identity_canonical": IDENTITY_CANONICAL_VERSION,
    "session_ns": str(SESSION_NS),
    "adapters_version": ADAPTERS_VERSION,
}
# A mismatch on any of these forces a drop + rebuild (§3.2).
_GATED_KEYS = ("schema_version", "identity_canonical", "session_ns", "adapters_version")

_DDL = """
CREATE TABLE IF NOT EXISTS schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS block (
  id                 INTEGER PRIMARY KEY,
  hash               TEXT    NOT NULL UNIQUE,
  kind               TEXT    NOT NULL,
  text               TEXT    NOT NULL DEFAULT '',
  identity_canonical TEXT    NOT NULL,
  n_tokens           INTEGER,
  created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  CHECK (kind IN ('text','tool_use','tool_result','thinking','image','system','tool_def','unknown'))
);
CREATE INDEX IF NOT EXISTS block_kind ON block(kind);

CREATE TABLE IF NOT EXISTS session (
  session_id        TEXT PRIMARY KEY,
  provider          TEXT NOT NULL,
  cli               TEXT,
  run_id            TEXT NOT NULL,
  cwd               TEXT NOT NULL,
  workspace_slug    TEXT NOT NULL,
  workspace_hash    TEXT NOT NULL,
  native_session_id TEXT,
  minted            INTEGER NOT NULL DEFAULT 0,
  source_descriptor TEXT,
  started_at        TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS session_native
  ON session(run_id, provider, native_session_id)
  WHERE native_session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS session_run       ON session(run_id);
CREATE INDEX IF NOT EXISTS session_workspace ON session(workspace_hash);

CREATE TABLE IF NOT EXISTS wire_exchange (
  exchange_id        TEXT PRIMARY KEY,
  session_id         TEXT,
  run_id             TEXT NOT NULL,
  provider           TEXT NOT NULL,
  model              TEXT NOT NULL,
  ts                 TEXT NOT NULL,
  seq                INTEGER,
  req_system_chars   INTEGER,
  req_tools_chars    INTEGER,
  req_messages_chars INTEGER,
  req_tokens         INTEGER,
  res_tokens         INTEGER,
  stop_reason        TEXT,
  mutated_manually   INTEGER NOT NULL DEFAULT 0,
  raw_dir            TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES session(session_id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS wire_exchange_session ON wire_exchange(session_id, seq);
CREATE INDEX IF NOT EXISTS wire_exchange_run     ON wire_exchange(run_id);
CREATE INDEX IF NOT EXISTS wire_exchange_ts      ON wire_exchange(ts);

CREATE TABLE IF NOT EXISTS transcript_turn (
  turn_id      TEXT PRIMARY KEY,
  session_id   TEXT NOT NULL,
  run_id       TEXT NOT NULL,
  provider     TEXT NOT NULL,
  cli          TEXT NOT NULL,
  parent_id    TEXT,
  role         TEXT NOT NULL,
  seq          INTEGER NOT NULL,
  ts           TEXT,
  is_sidechain INTEGER NOT NULL DEFAULT 0,
  model        TEXT,
  source_path  TEXT NOT NULL,
  source_line  INTEGER,
  FOREIGN KEY (session_id) REFERENCES session(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS transcript_turn_session ON transcript_turn(session_id, seq);
CREATE INDEX IF NOT EXISTS transcript_turn_parent  ON transcript_turn(parent_id);
CREATE INDEX IF NOT EXISTS transcript_turn_run     ON transcript_turn(run_id);

CREATE TABLE IF NOT EXISTS exchange_block (
  exchange_id TEXT    NOT NULL,
  pos         INTEGER NOT NULL,
  block_id    INTEGER NOT NULL,
  role        TEXT    NOT NULL,
  section     TEXT    NOT NULL,
  PRIMARY KEY (exchange_id, pos),
  FOREIGN KEY (exchange_id) REFERENCES wire_exchange(exchange_id) ON DELETE CASCADE,
  FOREIGN KEY (block_id)    REFERENCES block(id)
);
CREATE INDEX IF NOT EXISTS exchange_block_block ON exchange_block(block_id);

CREATE TABLE IF NOT EXISTS turn_block (
  turn_id  TEXT    NOT NULL,
  pos      INTEGER NOT NULL,
  block_id INTEGER NOT NULL,
  role     TEXT    NOT NULL,
  PRIMARY KEY (turn_id, pos),
  FOREIGN KEY (turn_id)  REFERENCES transcript_turn(turn_id) ON DELETE CASCADE,
  FOREIGN KEY (block_id) REFERENCES block(id)
);
CREATE INDEX IF NOT EXISTS turn_block_block ON turn_block(block_id);

CREATE VIRTUAL TABLE IF NOT EXISTS block_fts USING fts5(
  text,
  content       = 'block',
  content_rowid = 'id',
  tokenize      = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS block_ai AFTER INSERT ON block BEGIN
  INSERT INTO block_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS block_ad AFTER DELETE ON block BEGIN
  INSERT INTO block_fts(block_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""

# Reverse-dependency drop order (triggers + FTS first, then edges, entities, block, meta).
_DROP_DDL = """
DROP TRIGGER IF EXISTS block_ai;
DROP TRIGGER IF EXISTS block_ad;
DROP TABLE IF EXISTS block_fts;
DROP TABLE IF EXISTS turn_block;
DROP TABLE IF EXISTS exchange_block;
DROP TABLE IF EXISTS transcript_turn;
DROP TABLE IF EXISTS wire_exchange;
DROP TABLE IF EXISTS session;
DROP TABLE IF EXISTS block;
DROP TABLE IF EXISTS schema_meta;
"""


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create the tier-2 schema (idempotent) and seed schema_meta.

    Self-healing version gate (§3.2): if an existing schema_meta mismatches the code
    constants on any gated key, drop the whole schema and rebuild it empty. tier-2 is a
    rebuildable projection, so replaying tier-1 into the fresh schema is a later slice
    (§10.5); this gate guarantees the on-disk shape always matches the running code.
    """
    if _gated_mismatch(conn):
        conn.executescript(_DROP_DDL)
    conn.executescript(_DDL)
    _seed_schema_meta(conn)


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Rebuild the external-content FTS index from the block table (§3.6)."""
    conn.execute("INSERT INTO block_fts(block_fts) VALUES ('rebuild')")


def _gated_mismatch(conn: sqlite3.Connection) -> bool:
    if not _has_table(conn, "schema_meta"):
        return False  # fresh db: nothing to rebuild; apply_schema creates + seeds below
    stored = dict(conn.execute("SELECT key, value FROM schema_meta").fetchall())
    # A MISSING gated key (an old shape predating the key, e.g. before adapters_version) is a
    # mismatch too: stored.get returns None, which never equals the code constant, so it forces
    # drop + rebuild rather than silently seeding the new key onto the stale schema (§3.2).
    return any(stored.get(key) != _SCHEMA_META[key] for key in _GATED_KEYS)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _seed_schema_meta(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO schema_meta(key, value) VALUES (?, ?)",
        list(_SCHEMA_META.items()),
    )
