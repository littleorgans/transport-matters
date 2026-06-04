"""Tier-2 connection management: the §3.1 PRAGMAs, the db path, and a transaction helper.

`index` sits after `storage` in the import DAG and imports only `ir`, `canonicalization`,
and these small path/connection helpers — never `storage` internals or `server`.
"""

import sqlite3
from contextlib import contextmanager
from typing import TYPE_CHECKING

from transport_matters.storage_roots import default_storage_root

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# Applied on every connection, in this order (§3.1). WAL + busy_timeout is the
# single-writer discipline at the file level; synchronous=NORMAL is safe because tier-2 is
# a rebuildable projection of tier-1.
_PRAGMAS = (
    "PRAGMA journal_mode = WAL",
    "PRAGMA foreign_keys = ON",
    "PRAGMA busy_timeout = 5000",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA wal_autocheckpoint = 1000",
)

# Read connections (§8.1) skip the WAL/sync/checkpoint write-tuning PRAGMAs — the file is
# already WAL — and set query_only=ON, which rejects writes. Under WAL a reader sees a
# consistent snapshot and never blocks the §6 writer thread (nor each other). query_only is
# used rather than mode=ro to sidestep read-only-WAL lock pitfalls while giving the same
# never-write / never-block guarantees.
_READ_PRAGMAS = (
    "PRAGMA busy_timeout = 5000",
    "PRAGMA query_only = ON",
)


def index_db_path() -> Path:
    """Return the single tier-2 database path: ``default_storage_root()/index.db``."""
    return default_storage_root() / "index.db"


def connect(path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a tier-2 connection in manual-transaction mode with the appropriate PRAGMAs.

    ``read_only=True`` opens a pure reader for the §8 query surface (``query_only = ON``);
    otherwise the full §3.1 write PRAGMAs apply. ``isolation_level=None`` puts pysqlite in
    autocommit mode so the writer owns its transaction boundaries explicitly (§6.3).

    A read connection sets ``check_same_thread=False``: a request opens it in the read-only
    dependency and a **sync** route handler reads it, both of which FastAPI runs on its
    threadpool (so the blocking SQL stays off the event loop) — possibly on different worker
    threads. Access is sequential and per-request (never shared concurrently), so cross-thread
    use is safe. The writer connection stays thread-affine (``check_same_thread=True``).
    """
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=not read_only)
    for pragma in _READ_PRAGMAS if read_only else _PRAGMAS:
        conn.execute(pragma)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a body inside one ``BEGIN IMMEDIATE`` … ``COMMIT``, rolling back on any exception."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
