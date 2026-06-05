"""Shared fixtures for the index unit tests (real temp SQLite, never mocks; §13).

A ``conftest.py`` rather than an imported fixture so test modules reference ``conn`` as a
plain parameter (auto-discovered by pytest) without a module-level binding to shadow.
"""

from typing import TYPE_CHECKING

import pytest

from transport_matters.index.adapters.base import SessionBinding
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


def make_binding(
    session_id: str,
    *,
    provider: str = "anthropic",
    cli: str | None = "claude",
    run_id: str = "run1",
    cwd: str = "/w",
    workspace_slug: str = "slug",
    workspace_hash: str = "hash",
    started_at: str = "t",
    native_session_id: str | None = None,
    minted: bool = False,
) -> SessionBinding:
    """The one canonical ``SessionBinding`` factory for index tests (§4.2).

    ``native_session_id`` defaults to ``session_id`` (the claude/anthropic direct case); read-back
    callers pass a distinct native id. Per-test helpers delegate here so the binding shape lives in
    exactly one place.
    """
    return SessionBinding(
        session_id=session_id,
        provider=provider,
        run_id=run_id,
        cwd=cwd,
        workspace_slug=workspace_slug,
        workspace_hash=workspace_hash,
        started_at=started_at,
        cli=cli,
        native_session_id=native_session_id if native_session_id is not None else session_id,
        minted=minted,
    )
