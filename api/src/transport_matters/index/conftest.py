"""Shared fixtures for the index unit tests (real temp SQLite, never mocks; §13).

A ``conftest.py`` rather than an imported fixture so test modules reference ``conn`` as a
plain parameter (auto-discovered by pytest) without a module-level binding to shadow.
"""

from typing import TYPE_CHECKING

import pytest

from transport_matters.index.db import connect
from transport_matters.index.schema import apply_schema

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A real temp-file tier-2 connection with the schema applied, closed on teardown."""
    connection = connect(tmp_path / "index.db")
    apply_schema(connection)
    try:
        yield connection
    finally:
        connection.close()
