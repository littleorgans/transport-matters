from __future__ import annotations

import json
import logging
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlsplit
from uuid import uuid4

from psycopg import Error, sql

from transport_matters.config import (
    TEST_DB_PREFIX,
    Settings,
    database_url_with_database_name,
    resolve_test_database_url,
)
from transport_matters.session.migrate import upgrade_to_head
from transport_matters.session.pool import connect

STALE_TEMPLATE_MIN_AGE = timedelta(minutes=15)
TEMPLATE_DB_PREFIX = f"{TEST_DB_PREFIX}template_"
_TEMPLATE_METADATA_KIND = "transport_matters.test_template.v1"
logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from psycopg import Connection
    from psycopg.rows import DictRow


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
        test_db = cls(resolved_admin_url, database_url, database_name)
        try:
            _clone_database_from_template(resolved_admin_url, database_name, template_name)
        except Exception:
            test_db.drop()
            raise
        return test_db

    @classmethod
    def ensure_template(cls, admin_url: str) -> str:
        worker = _worker_name()
        key = f"{admin_url}|{worker}"
        if key in cls._template_names:
            return cls._template_names[key][1]

        digest = sha256(f"{admin_url}|{worker}|{os.getpid()}".encode()).hexdigest()[:12]
        database_name = f"{TEST_DB_PREFIX}template_{worker}_{digest}"
        database_url = database_url_for(admin_url, database_name)
        _create_database(admin_url, database_name)
        template_db = cls(admin_url, database_url, database_name)
        try:
            template_db.migrate()
            _set_template_metadata(admin_url, database_name)
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

    @classmethod
    def drop_stale_templates(
        cls,
        admin_url: str | None = None,
        *,
        min_age: timedelta = STALE_TEMPLATE_MIN_AGE,
    ) -> list[str]:
        resolved_admin_url = admin_url or resolve_test_database_url(Settings.load())
        cutoff = datetime.now(UTC) - min_age
        dropped: list[str] = []
        for database_name in _stale_template_database_names(resolved_admin_url, cutoff):
            template_db = cls(
                resolved_admin_url,
                database_url_for(resolved_admin_url, database_name),
                database_name,
            )
            template_db.drop()
            dropped.append(database_name)
        return dropped

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
    return database_url_with_database_name(admin_url, database_name)


def _worker_name() -> str:
    raw = os.environ.get("PYTEST_XDIST_WORKER", "gw_main")
    safe = "".join(char if char.isalnum() else "_" for char in raw.lower())
    return safe[:16] or "gw_main"


def _create_database(admin_url: str, database_name: str) -> None:
    with connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))


def _clone_database_from_template(admin_url: str, database_name: str, template_name: str) -> None:
    with connect(admin_url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(database_name),
                sql.Identifier(template_name),
            )
        )


def _set_template_metadata(admin_url: str, database_name: str) -> None:
    metadata = _template_metadata()
    with connect(admin_url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(database_name),
                sql.Literal(metadata),
            )
        )


def _template_metadata(
    *,
    created_at: datetime | None = None,
    owner_host: str | None = None,
    owner_pid: int | None = None,
) -> str:
    return json.dumps(
        {
            "kind": _TEMPLATE_METADATA_KIND,
            "created_at": (created_at or datetime.now(UTC)).isoformat(),
            "owner_host": owner_host or socket.gethostname(),
            "owner_pid": owner_pid if owner_pid is not None else os.getpid(),
        },
        sort_keys=True,
    )


def _stale_template_database_names(admin_url: str, cutoff: datetime) -> list[str]:
    stale: list[str] = []
    with connect(admin_url, autocommit=True) as conn:
        rows = conn.execute(
            """
            SELECT
                d.oid,
                d.datname,
                shobj_description(d.oid, 'pg_database') AS description,
                (
                    SELECT count(*)
                    FROM pg_stat_activity a
                    WHERE a.datname = d.datname
                      AND a.pid <> pg_backend_pid()
                ) AS active_connections
            FROM pg_database d
            WHERE left(d.datname, %s) = %s
            """,
            (len(TEMPLATE_DB_PREFIX), TEMPLATE_DB_PREFIX),
        ).fetchall()
        for row in rows:
            if row["active_connections"]:
                continue
            metadata = _parse_template_metadata(row["description"])
            if _template_owner_is_alive(metadata):
                continue
            created_at = _template_created_at(metadata) or _database_created_at(conn, row["oid"])
            if created_at is None or created_at > cutoff:
                continue
            stale.append(row["datname"])
    return stale


def _parse_template_metadata(description: object) -> dict[str, object]:
    if not isinstance(description, str):
        return {}
    try:
        metadata = json.loads(description)
    except json.JSONDecodeError:
        return {}
    if not isinstance(metadata, dict) or metadata.get("kind") != _TEMPLATE_METADATA_KIND:
        return {}
    return metadata


def _template_created_at(metadata: dict[str, object]) -> datetime | None:
    raw_created_at = metadata.get("created_at")
    if not isinstance(raw_created_at, str):
        return None
    try:
        created_at = datetime.fromisoformat(raw_created_at)
    except ValueError:
        return None
    if created_at.tzinfo is None:
        return created_at.replace(tzinfo=UTC)
    return created_at.astimezone(UTC)


def _database_created_at(conn: Connection[DictRow], oid: object) -> datetime | None:
    try:
        row = conn.execute(
            "SELECT (pg_stat_file(%s)).modification AS created_at",
            (f"base/{oid}/PG_VERSION",),
        ).fetchone()
    except Error:
        logger.debug("Could not read test template database creation time", exc_info=True)
        return None
    created_at = row["created_at"] if row else None
    if not isinstance(created_at, datetime):
        return None
    if created_at.tzinfo is None:
        return created_at.replace(tzinfo=UTC)
    return created_at.astimezone(UTC)


def _template_owner_is_alive(metadata: dict[str, object]) -> bool:
    owner_host = metadata.get("owner_host")
    if isinstance(owner_host, str) and owner_host != socket.gethostname():
        return True
    owner_pid = metadata.get("owner_pid")
    if not isinstance(owner_pid, int) or owner_pid <= 0:
        return False
    try:
        os.kill(owner_pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
