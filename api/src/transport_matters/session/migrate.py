"""Alembic migration machinery shared by the runtime and the test harness.

The runtime auto-migrates the configured session store on backend startup (see
``main.lifespan``); the test harness (``session.testing``) and the ``db`` CLI command
group reuse the same helpers so there is exactly one migrator. Single-instance and
multi-instance launches share one Postgres, so :func:`apply_migrations` guards the
upgrade with a session-level advisory lock and only runs when the store is behind head.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from transport_matters.session.pool import connect, sqlalchemy_url

# Stable, project-owned bigint key for pg_advisory_lock so concurrent launches against
# one Postgres serialize their migration attempt instead of racing DDL ("tmmig").
_MIGRATION_ADVISORY_LOCK_KEY = 0x746D6D6967


class MigrationError(RuntimeError):
    """Raised when applying the session-store schema migration fails."""


def migrations_dir() -> Path:
    current = Path(__file__).resolve()
    for candidate in (current.parents[3] / "migrations", current.parents[2] / "migrations"):
        if candidate.exists():
            return candidate
    return current.parents[3] / "migrations"


def alembic_config(database_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir()))
    cfg.set_main_option("sqlalchemy.url", sqlalchemy_url(database_url))
    return cfg


def migration_head() -> str:
    """Return the head revision id defined by the packaged migration scripts."""
    cfg = Config()
    cfg.set_main_option("script_location", str(migrations_dir()))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    if head is None:
        raise MigrationError("no alembic head revision found in migrations/")
    return head


def current_revision(database_url: str) -> str | None:
    """Return the revision the database is stamped at, or ``None`` if unmigrated."""
    engine = create_engine(sqlalchemy_url(database_url))
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()


def upgrade_to_head(database_url: str) -> None:
    """Run ``alembic upgrade head`` against ``database_url``."""
    command.upgrade(alembic_config(database_url), "head")


def apply_migrations(database_url: str) -> None:
    """Bring the session store to head if behind, serialized by an advisory lock.

    Fast path: when already at head, returns without taking the lock or running DDL, so
    normal boots are cheap. Otherwise acquires a session-level ``pg_advisory_lock``,
    re-checks under the lock (so a concurrent launch that just migrated is a no-op), and
    upgrades. Raises :class:`MigrationError` if the upgrade fails.
    """
    head = migration_head()
    if current_revision(database_url) == head:
        return
    with connect(database_url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_MIGRATION_ADVISORY_LOCK_KEY,))
        try:
            if current_revision(database_url) == head:
                return
            upgrade_to_head(database_url)
        except MigrationError:
            raise
        except Exception as exc:
            raise MigrationError(f"session store migration failed: {exc}") from exc
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_MIGRATION_ADVISORY_LOCK_KEY,))
