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


def index_db_path() -> Path:
    """Return the single tier-2 database path: ``default_storage_root()/index.db``."""
    return default_storage_root() / "index.db"


def connect(path: str | Path) -> sqlite3.Connection:
    """Open a tier-2 connection with the §3.1 PRAGMAs applied, in manual-transaction mode.

    ``isolation_level=None`` puts pysqlite in autocommit mode so the writer owns its
    transaction boundaries explicitly (``BEGIN IMMEDIATE`` / ``SAVEPOINT`` / ``COMMIT``,
    §6.3) rather than the driver inserting implicit ``BEGIN`` statements.
    """
    conn = sqlite3.connect(path, isolation_level=None)
    for pragma in _PRAGMAS:
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
