"""Tests for the ``transport-matters db`` status/upgrade command group."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from transport_matters import config
from transport_matters.cli import main
from transport_matters.session.pool import connect
from transport_matters.session.testing import TestDb

if TYPE_CHECKING:
    from collections.abc import Iterator

runner = CliRunner()


@pytest.fixture
def fresh_db() -> Iterator[TestDb]:
    db = TestDb.create()
    try:
        yield db
    finally:
        db.drop()


def test_db_status_reports_up_to_date(fresh_db: TestDb, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRANSPORT_MATTERS_DATABASE_URL", fresh_db.database_url)
    config.get_settings.cache_clear()

    result = runner.invoke(main, ["db", "status"])

    assert result.exit_code == 0, result.output
    assert "up to date" in result.output
    assert ":***@" in result.output  # password redacted
    assert ":tm@" not in result.output


def test_db_status_unconfigured_exits_2(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRANSPORT_MATTERS_HOME", str(tmp_path))
    monkeypatch.delenv("TRANSPORT_MATTERS_DATABASE_URL", raising=False)
    config.get_settings.cache_clear()

    result = runner.invoke(main, ["db", "status"])

    assert result.exit_code == 2


def test_db_upgrade_brings_unmigrated_db_to_head(
    fresh_db: TestDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    with connect(fresh_db.database_url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS event_dead_letter CASCADE")
        conn.execute("DROP TABLE IF EXISTS event_artifact CASCADE")
        conn.execute("DROP TABLE IF EXISTS event CASCADE")
        conn.execute("DROP TABLE IF EXISTS artifact CASCADE")
        conn.execute("DROP TABLE IF EXISTS session CASCADE")
        conn.execute("DROP TABLE IF EXISTS alembic_version")
    monkeypatch.setenv("TRANSPORT_MATTERS_DATABASE_URL", fresh_db.database_url)
    config.get_settings.cache_clear()

    result = runner.invoke(main, ["db", "upgrade"])

    assert result.exit_code == 0, result.output
    assert "at head" in result.output
