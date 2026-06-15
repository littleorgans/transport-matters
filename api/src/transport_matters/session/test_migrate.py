"""Tests for the shared alembic migration machinery (runtime + tests)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from alembic import command
from psycopg.errors import CheckViolation

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
_DEAD_LETTER_INDEXES = frozenset({"event_dead_letter_run_ix", "event_dead_letter_span_uq"})
_REDUNDANT_SESSION_SEQ_INDEX = "event_session_seq_ix"
_SESSION_CLASSIFICATION_COLUMNS = frozenset({"session_purpose", "session_visibility"})


def _reset_to_unmigrated(database_url: str) -> None:
    with connect(database_url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS event_dead_letter CASCADE")
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


def _dead_letter_indexes(database_url: str) -> frozenset[str]:
    with connect(database_url, autocommit=True) as conn:
        rows = conn.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'event_dead_letter'
            """
        ).fetchall()
    return frozenset(row["indexname"] for row in rows)


def _session_columns(database_url: str) -> frozenset[str]:
    with connect(database_url, autocommit=True) as conn:
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'session'
            """
        ).fetchall()
    return frozenset(row["column_name"] for row in rows)


def _assert_dead_letter_present(database_url: str) -> None:
    with connect(database_url, autocommit=True) as conn:
        exists = conn.execute("SELECT to_regclass('public.event_dead_letter')").fetchone()
    assert exists is not None
    assert exists["to_regclass"] == "event_dead_letter"
    assert _dead_letter_indexes(database_url) >= _DEAD_LETTER_INDEXES


def _assert_session_classification_present(database_url: str) -> None:
    assert _session_columns(database_url) >= _SESSION_CLASSIFICATION_COLUMNS


def _assert_session_classification_absent(database_url: str) -> None:
    assert _session_columns(database_url).isdisjoint(_SESSION_CLASSIFICATION_COLUMNS)


def _insert_legacy_session(database_url: str) -> None:
    with connect(database_url, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO "session" (
                session_id, provider, cli, run_id, cwd, workspace_slug, workspace_hash,
                native_session_id, minted, owner, status, started_at
            ) VALUES (
                'legacy-session', 'anthropic', 'claude', 'run1', '/workspace',
                'workspace', 'hash1', 'native1', true, 'local', 'active',
                '2026-06-06T00:00:00Z'
            )
            """
        )


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
    _assert_dead_letter_present(test_db.database_url)
    _assert_session_classification_present(test_db.database_url)

    command.downgrade(migrate.alembic_config(test_db.database_url), "-1")

    assert migrate.current_revision(test_db.database_url) == "0003_event_dead_letter"
    _assert_session_classification_absent(test_db.database_url)
    _assert_dead_letter_present(test_db.database_url)
    _assert_tier1_indexes_present(test_db.database_url)

    command.downgrade(migrate.alembic_config(test_db.database_url), "-1")

    assert migrate.current_revision(test_db.database_url) == "0002_event_tier1_indexes"
    assert not _dead_letter_indexes(test_db.database_url)
    _assert_tier1_indexes_present(test_db.database_url)

    migrate.apply_migrations(test_db.database_url)

    assert migrate.current_revision(test_db.database_url) == migrate.migration_head()
    _assert_tier1_indexes_present(test_db.database_url)
    _assert_dead_letter_present(test_db.database_url)
    _assert_session_classification_present(test_db.database_url)


def test_session_classification_migration_backfills_checks_and_downgrades(
    test_db: TestDb,
) -> None:
    _reset_to_unmigrated(test_db.database_url)
    cfg = migrate.alembic_config(test_db.database_url)
    command.upgrade(cfg, "0003_event_dead_letter")
    _insert_legacy_session(test_db.database_url)

    command.upgrade(cfg, "head")

    _assert_session_classification_present(test_db.database_url)
    with connect(test_db.database_url, autocommit=True) as conn:
        row = conn.execute(
            """
            SELECT session_purpose, session_visibility
            FROM "session"
            WHERE session_id = 'legacy-session'
            """
        ).fetchone()
        assert row is not None
        assert row["session_purpose"] == "user"
        assert row["session_visibility"] == "user_visible"

        with pytest.raises(CheckViolation):
            conn.execute(
                "UPDATE \"session\" SET session_purpose = 'bogus' WHERE session_id = 'legacy-session'"
            )
        with pytest.raises(CheckViolation):
            conn.execute(
                "UPDATE \"session\" SET session_visibility = 'bogus' WHERE session_id = 'legacy-session'"
            )

    command.downgrade(cfg, "-1")

    assert migrate.current_revision(test_db.database_url) == "0003_event_dead_letter"
    _assert_session_classification_absent(test_db.database_url)


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
