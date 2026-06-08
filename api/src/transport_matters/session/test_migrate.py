"""Tests for the shared alembic migration machinery (runtime + tests)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from alembic import command

from transport_matters.session import migrate
from transport_matters.session.pool import connect

if TYPE_CHECKING:
    from transport_matters.session.testing import TestDb


_FOUNDATION_EVENT_INDEXES = frozenset({"event_fts_gin", "event_ir_gin"})
_TIER1_EVENT_INDEXES = frozenset(
    {
        "event_raw_gin",
        "event_session_attachment_type_expr_ix",
        "event_session_raw_type_expr_ix",
    }
)
_REDUNDANT_SESSION_SEQ_INDEX = "event_session_seq_ix"


def _reset_to_unmigrated(database_url: str) -> None:
    with connect(database_url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS event_artifact CASCADE")
        conn.execute("DROP TABLE IF EXISTS event CASCADE")
        conn.execute("DROP TABLE IF EXISTS artifact CASCADE")
        conn.execute("DROP TABLE IF EXISTS session CASCADE")
        conn.execute("DROP TABLE IF EXISTS alembic_version")


def _event_indexes(database_url: str) -> dict[str, str]:
    with connect(database_url, autocommit=True) as conn:
        rows = conn.execute(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'event'
            """
        ).fetchall()
    indexes: dict[str, str] = {}
    for row in rows:
        indexes[row["indexname"]] = row["indexdef"]
    return indexes


def _assert_tier1_indexes_present(database_url: str) -> None:
    indexes = _event_indexes(database_url)
    index_names = frozenset(indexes)
    assert index_names >= _TIER1_EVENT_INDEXES
    assert index_names >= _FOUNDATION_EVENT_INDEXES
    assert _REDUNDANT_SESSION_SEQ_INDEX not in index_names
    assert "(session_id, seq)" in indexes["event_pkey"]


def test_migration_head_is_defined() -> None:
    assert migrate.migration_head()  # non-empty revision id


def test_current_revision_none_on_unmigrated_db(test_db: TestDb) -> None:
    # A freshly created test db is at head; reset it to simulate an unmigrated store.
    _reset_to_unmigrated(test_db.database_url)
    assert migrate.current_revision(test_db.database_url) is None


def test_apply_migrations_brings_unmigrated_db_to_head(test_db: TestDb) -> None:
    _reset_to_unmigrated(test_db.database_url)
    assert migrate.current_revision(test_db.database_url) is None

    migrate.apply_migrations(test_db.database_url)

    assert migrate.current_revision(test_db.database_url) == migrate.migration_head()


def test_apply_migrations_noop_when_at_head(test_db: TestDb) -> None:
    # test_db is already migrated; a second apply must be a no-op and not raise.
    migrate.apply_migrations(test_db.database_url)
    assert migrate.current_revision(test_db.database_url) == migrate.migration_head()


def test_alembic_upgrade_and_downgrade_smoke(test_db: TestDb) -> None:
    _reset_to_unmigrated(test_db.database_url)

    migrate.apply_migrations(test_db.database_url)

    assert migrate.current_revision(test_db.database_url) == migrate.migration_head()
    _assert_tier1_indexes_present(test_db.database_url)

    command.downgrade(migrate.alembic_config(test_db.database_url), "-1")

    assert migrate.current_revision(test_db.database_url) == "0001_session_store"
    downgraded_indexes = frozenset(_event_indexes(test_db.database_url))
    assert not _TIER1_EVENT_INDEXES & downgraded_indexes
    assert downgraded_indexes >= _FOUNDATION_EVENT_INDEXES

    migrate.apply_migrations(test_db.database_url)

    assert migrate.current_revision(test_db.database_url) == migrate.migration_head()
    _assert_tier1_indexes_present(test_db.database_url)


def test_apply_migrations_raises_migration_error_on_failure(
    test_db: TestDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(migrate, "current_revision", lambda _url: "not-head")
    monkeypatch.setattr(migrate, "migration_head", lambda: "head-xyz")

    def boom(_url: str) -> None:
        raise RuntimeError("alembic blew up")

    monkeypatch.setattr(migrate, "upgrade_to_head", boom)

    with pytest.raises(migrate.MigrationError):
        migrate.apply_migrations(test_db.database_url)
