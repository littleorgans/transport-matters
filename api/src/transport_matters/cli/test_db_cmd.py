"""Tests for the ``transport-matters db`` status/upgrade command group."""

from __future__ import annotations

from typing import TYPE_CHECKING

from psycopg import sql
from typer.testing import CliRunner

from transport_matters import config, env_keys
from transport_matters.cli import main
from transport_matters.session.pool import connect

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest

    from transport_matters.session.testing import TestDb

runner = CliRunner()


def test_db_status_reports_up_to_date(
    test_db: TestDb,
    point_cli_at_channel_database: Callable[..., object],
) -> None:
    point_cli_at_channel_database(test_db)

    result = runner.invoke(main, ["db", "status"])

    assert result.exit_code == 0, result.output
    assert "up to date" in result.output
    assert test_db.database_name in result.output
    assert ":***@" in result.output  # password redacted
    assert ":tm@" not in result.output


def test_db_status_unconfigured_exits_2(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(env_keys.HOME, str(tmp_path))
    monkeypatch.delenv(env_keys.DATABASE_URL, raising=False)
    config.get_settings.cache_clear()

    result = runner.invoke(main, ["db", "status"])

    assert result.exit_code == 2


def test_db_upgrade_brings_unmigrated_db_to_head(
    temporary_channel_database: TestDb,
    point_cli_at_channel_database: Callable[..., object],
) -> None:
    with connect(temporary_channel_database.admin_url, autocommit=True) as conn:
        conn.execute(
            sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(temporary_channel_database.database_name)
            )
        )
    point_cli_at_channel_database(temporary_channel_database)

    result = runner.invoke(main, ["db", "upgrade"])

    assert result.exit_code == 0, result.output
    assert "at head" in result.output
