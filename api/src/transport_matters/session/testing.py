from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

from psycopg import sql

from transport_matters.config import Settings, resolve_test_database_url
from transport_matters.session.migrate import upgrade_to_head
from transport_matters.session.pool import connect

_MIGRATED_TABLES = (
    "canvas",
    "space_worktree",
    "space_git_identity",
    "space",
    "event_dead_letter",
    "event_artifact",
    "event",
    "artifact",
    "session",
    "alembic_version",
)


@dataclass(frozen=True)
class TestDb:
    __test__ = False

    admin_url: str
    database_url: str
    database_name: str

    @classmethod
    def create(cls, admin_url: str | None = None) -> TestDb:
        resolved_admin_url = admin_url or resolve_test_database_url(Settings.load())
        database_name = f"tm_test_{os.getpid()}_{uuid4().hex}"
        database_url = database_url_for(resolved_admin_url, database_name)
        with connect(resolved_admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        test_db = cls(resolved_admin_url, database_url, database_name)
        try:
            test_db.migrate()
        except Exception:
            test_db.drop()
            raise
        return test_db

    def migrate(self) -> None:
        upgrade_to_head(self.database_url)

    def reset_to_unmigrated(self) -> None:
        with connect(self.database_url, autocommit=True) as conn:
            for table_name in _MIGRATED_TABLES:
                conn.execute(
                    sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(table_name))
                )

    def drop(self) -> None:
        with connect(self.admin_url, autocommit=True) as conn:
            conn.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (self.database_name,),
            )
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(self.database_name))
            )


def database_url_for(admin_url: str, database_name: str) -> str:
    parts = urlsplit(admin_url)
    if not parts.scheme or not parts.netloc:
        raise ValueError("admin_url must be a PostgreSQL URL")
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{quote(database_name)}", parts.query, parts.fragment)
    )
