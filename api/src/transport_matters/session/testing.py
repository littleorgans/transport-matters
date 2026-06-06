from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

from alembic import command
from alembic.config import Config
from psycopg import sql

from transport_matters.session.pool import connect, sqlalchemy_url
from transport_matters.session_config import DEFAULT_TEST_ADMIN_DATABASE_URL

TEST_ADMIN_DATABASE_URL_ENV = "TRANSPORT_MATTERS_TEST_ADMIN_DATABASE_URL"


@dataclass(frozen=True)
class TestDb:
    __test__ = False

    admin_url: str
    database_url: str
    database_name: str

    @classmethod
    def create(cls, admin_url: str | None = None) -> TestDb:
        resolved_admin_url = admin_url or os.environ.get(
            TEST_ADMIN_DATABASE_URL_ENV, DEFAULT_TEST_ADMIN_DATABASE_URL
        )
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
        command.upgrade(alembic_config(self.database_url), "head")

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


def database_url_for(admin_url: str, database_name: str) -> str:
    parts = urlsplit(admin_url)
    if not parts.scheme or not parts.netloc:
        raise ValueError("admin_url must be a PostgreSQL URL")
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{quote(database_name)}", parts.query, parts.fragment)
    )
