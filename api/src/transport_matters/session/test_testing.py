from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from psycopg import sql

from transport_matters.config import TEST_DB_PREFIX
from transport_matters.session import testing as testing_module
from transport_matters.session.pool import connect
from transport_matters.session.testing import TestDb, database_url_for


def test_drop_stale_templates_reaps_inactive_old_template(test_db: TestDb) -> None:
    template_name = f"{TEST_DB_PREFIX}template_stale_{uuid4().hex}"
    _create_template_database(test_db.admin_url, template_name, owner_pid=-1)

    try:
        assert _database_exists(test_db.admin_url, template_name)

        dropped = TestDb.drop_stale_templates(test_db.admin_url, min_age=timedelta(seconds=0))
        assert template_name in dropped

        assert not _database_exists(test_db.admin_url, template_name)
    finally:
        TestDb(
            test_db.admin_url,
            database_url_for(test_db.admin_url, template_name),
            template_name,
        ).drop()


def test_drop_stale_templates_keeps_active_template(test_db: TestDb) -> None:
    template_name = f"{TEST_DB_PREFIX}template_active_{uuid4().hex}"
    template_url = database_url_for(test_db.admin_url, template_name)
    _create_template_database(test_db.admin_url, template_name, owner_pid=-1)

    try:
        with connect(template_url):
            dropped = TestDb.drop_stale_templates(test_db.admin_url, min_age=timedelta(seconds=0))
            assert template_name not in dropped

        assert _database_exists(test_db.admin_url, template_name)
    finally:
        TestDb(test_db.admin_url, template_url, template_name).drop()


def test_drop_stale_templates_matches_literal_prefix(test_db: TestDb) -> None:
    decoy_name = f"tmXtestXtemplateZdecoy_{uuid4().hex}"
    decoy_url = database_url_for(test_db.admin_url, decoy_name)
    _create_template_database(test_db.admin_url, decoy_name, owner_pid=-1)

    try:
        dropped = TestDb.drop_stale_templates(test_db.admin_url, min_age=timedelta(seconds=0))

        assert decoy_name not in dropped
        assert _database_exists(test_db.admin_url, decoy_name)
    finally:
        TestDb(test_db.admin_url, decoy_url, decoy_name).drop()


def test_create_drops_clone_after_partial_clone_failure(
    test_db: TestDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    created_names: list[str] = []

    def clone_then_fail(admin_url: str, database_name: str, template_name: str) -> None:
        del template_name
        created_names.append(database_name)
        with connect(admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        raise RuntimeError("clone failed after create")

    monkeypatch.setattr(testing_module, "_clone_database_from_template", clone_then_fail)

    with pytest.raises(RuntimeError, match="clone failed after create"):
        TestDb.create(test_db.admin_url)

    assert len(created_names) == 1
    assert not _database_exists(test_db.admin_url, created_names[0])


def _create_template_database(admin_url: str, database_name: str, *, owner_pid: int) -> None:
    created_at = datetime.now(UTC) - timedelta(days=1)
    description = testing_module._template_metadata(created_at=created_at, owner_pid=owner_pid)
    with connect(admin_url, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        conn.execute(
            sql.SQL("COMMENT ON DATABASE {} IS {}").format(
                sql.Identifier(database_name),
                sql.Literal(description),
            )
        )


def _database_exists(admin_url: str, database_name: str) -> bool:
    with connect(admin_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (database_name,),
        ).fetchone()
    return row is not None
