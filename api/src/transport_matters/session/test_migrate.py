"""Tests for the shared alembic migration machinery (runtime + tests)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from transport_matters.session import migrate
from transport_matters.session.pool import connect

if TYPE_CHECKING:
    from transport_matters.session.testing import TestDb


def test_migration_head_is_defined() -> None:
    assert migrate.migration_head()  # non-empty revision id


def test_current_revision_none_on_unmigrated_db(test_db: TestDb) -> None:
    # A freshly created+migrated test db is at head; drop the version table to simulate unmigrated.
    with connect(test_db.database_url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS alembic_version")
    assert migrate.current_revision(test_db.database_url) is None


def test_apply_migrations_brings_unmigrated_db_to_head(test_db: TestDb) -> None:
    with connect(test_db.database_url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS event_artifact CASCADE")
        conn.execute("DROP TABLE IF EXISTS event CASCADE")
        conn.execute("DROP TABLE IF EXISTS artifact CASCADE")
        conn.execute("DROP TABLE IF EXISTS session CASCADE")
        conn.execute("DROP TABLE IF EXISTS alembic_version")

    assert migrate.current_revision(test_db.database_url) is None

    migrate.apply_migrations(test_db.database_url)

    assert migrate.current_revision(test_db.database_url) == migrate.migration_head()


def test_apply_migrations_noop_when_at_head(test_db: TestDb) -> None:
    # test_db is already migrated; a second apply must be a no-op and not raise.
    migrate.apply_migrations(test_db.database_url)
    assert migrate.current_revision(test_db.database_url) == migrate.migration_head()


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
