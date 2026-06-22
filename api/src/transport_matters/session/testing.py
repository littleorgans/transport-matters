from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from typing import ClassVar
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

from psycopg import sql

from transport_matters.config import TEST_DB_PREFIX, Settings, resolve_test_database_url
from transport_matters.session.migrate import upgrade_to_head
from transport_matters.session.pool import connect


@dataclass(frozen=True)
class TestDb:
    __test__ = False
    _template_names: ClassVar[dict[str, tuple[str, str]]] = {}

    admin_url: str
    database_url: str
    database_name: str

    @classmethod
    def create(cls, admin_url: str | None = None) -> TestDb:
        resolved_admin_url = admin_url or resolve_test_database_url(Settings.load())
        database_name = f"{TEST_DB_PREFIX}{os.getpid()}_{uuid4().hex}"
        database_url = database_url_for(resolved_admin_url, database_name)
        template_name = cls.ensure_template(resolved_admin_url)
        with connect(resolved_admin_url, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(database_name),
                    sql.Identifier(template_name),
                )
            )
        return cls(resolved_admin_url, database_url, database_name)

    @classmethod
    def ensure_template(cls, admin_url: str) -> str:
        worker = _worker_name()
        key = f"{admin_url}|{worker}"
        if key in cls._template_names:
            return cls._template_names[key][1]

        digest = sha256(f"{admin_url}|{worker}|{os.getpid()}".encode()).hexdigest()[:12]
        database_name = f"{TEST_DB_PREFIX}template_{worker}_{digest}"
        database_url = database_url_for(admin_url, database_name)
        with connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        template_db = cls(admin_url, database_url, database_name)
        try:
            template_db.migrate()
        except Exception:
            template_db.drop()
            raise
        cls._template_names[key] = (admin_url, database_name)
        return database_name

    @classmethod
    def drop_templates(cls) -> None:
        for key, (admin_url, database_name) in list(cls._template_names.items()):
            template_db = cls(admin_url, database_url_for(admin_url, database_name), database_name)
            template_db.drop()
            cls._template_names.pop(key, None)

    def migrate(self) -> None:
        upgrade_to_head(self.database_url)

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


def _worker_name() -> str:
    raw = os.environ.get("PYTEST_XDIST_WORKER", "gw_main")
    safe = "".join(char if char.isalnum() else "_" for char in raw.lower())
    return safe[:16] or "gw_main"
