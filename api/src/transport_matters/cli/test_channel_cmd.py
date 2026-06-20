"""Tests for the ``transport-matters channel`` command group."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from typer.testing import CliRunner

import transport_matters.cli.channel_cmd as channel_cmd
from transport_matters import config, env_keys
from transport_matters.cli import main
from transport_matters.cli.desktop_runtime import (
    DesktopRuntimeRecord,
    desktop_record_path,
    write_desktop_record,
)
from transport_matters.session import migrate
from transport_matters.session.pool import connect

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

    from transport_matters.channel import ChannelSpec
    from transport_matters.session.testing import TestDb

runner = CliRunner()


def _database_exists(admin_url: str, database_name: str) -> bool:
    with connect(admin_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (database_name,),
        ).fetchone()
    return row is not None


def test_channel_list_outputs_specs() -> None:
    result = runner.invoke(main, ["channel", "list"])

    assert result.exit_code == 0, result.output
    assert "stable" in result.output
    assert "preview" in result.output
    assert "transport_matters" in result.output
    assert "transport_matters_preview" in result.output
    assert "8787" in result.output
    assert "8798" in result.output
    assert "pid" in result.output
    assert "Transport Matters Preview" in result.output
    assert "PREVIEW" in result.output


def test_channel_list_renders_live_desktop_pid(
    channel_spec_factory: Callable[[str], ChannelSpec],
    patch_channel_specs: Callable[..., None],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = replace(channel_spec_factory("tm_list"), home=tmp_path / "tm-home")
    patch_channel_specs(spec)
    monkeypatch.delenv(env_keys.HOME, raising=False)
    write_desktop_record(
        desktop_record_path(spec.home),
        DesktopRuntimeRecord(
            channel=spec.id,
            pid=4321,
            proxy_port=spec.proxy_port,
            web_port=spec.web_port,
            log_path=str(spec.home / "runtime" / "desktop.log"),
        ),
    )
    monkeypatch.setattr(
        "transport_matters.cli.desktop_runtime.is_pid_alive", lambda pid: pid == 4321
    )

    result = runner.invoke(main, ["channel", "list"])

    assert result.exit_code == 0, result.output
    assert "pid" in result.output
    assert "4321" in result.output


def test_channel_list_blanks_invalid_or_inaccessible_desktop_pid(
    channel_spec_factory: Callable[[str], ChannelSpec],
    patch_channel_specs: Callable[..., None],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = replace(channel_spec_factory("tm_list"), home=tmp_path / "tm-home")
    patch_channel_specs(spec)
    monkeypatch.delenv(env_keys.HOME, raising=False)
    write_desktop_record(
        desktop_record_path(spec.home),
        DesktopRuntimeRecord(
            channel=spec.id,
            pid=4321,
            proxy_port=spec.proxy_port,
            web_port=spec.web_port,
            log_path=str(spec.home / "runtime" / "desktop.log"),
        ),
    )

    def raise_permission(_pid: int) -> bool:
        raise PermissionError

    monkeypatch.setattr("transport_matters.cli.desktop_runtime.is_pid_alive", raise_permission)

    result = runner.invoke(main, ["channel", "list"])

    assert result.exit_code == 0, result.output
    assert "pid" in result.output
    assert "4321" not in result.output


def test_channel_ensure_db_creates_migrates_and_is_idempotent(
    temporary_channel_database: TestDb,
    channel_spec_factory: Callable[[str], ChannelSpec],
    patch_channel_specs: Callable[..., None],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = channel_spec_factory(temporary_channel_database.database_name)
    patch_channel_specs(spec)
    monkeypatch.setenv(env_keys.HOME, str(tmp_path))
    monkeypatch.setenv(env_keys.DATABASE_URL, temporary_channel_database.admin_url)
    config.get_settings.cache_clear()

    assert not _database_exists(
        temporary_channel_database.admin_url,
        temporary_channel_database.database_name,
    )

    result = runner.invoke(main, ["channel", "ensure-db", "tmp"])

    assert result.exit_code == 0, result.output
    assert _database_exists(
        temporary_channel_database.admin_url,
        temporary_channel_database.database_name,
    )
    assert (
        migrate.current_revision(temporary_channel_database.database_url)
        == migrate.migration_head()
    )
    assert "created" in result.output
    assert temporary_channel_database.database_name in result.output

    rerun = runner.invoke(main, ["channel", "ensure-db", "tmp"])

    assert rerun.exit_code == 0, rerun.output
    assert "exists" in rerun.output
    assert (
        migrate.current_revision(temporary_channel_database.database_url)
        == migrate.migration_head()
    )


def test_channel_ensure_db_without_configured_server_exits_2(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(env_keys.HOME, str(tmp_path))
    monkeypatch.delenv(env_keys.DATABASE_URL, raising=False)
    config.get_settings.cache_clear()

    result = runner.invoke(main, ["channel", "ensure-db", "preview"])

    assert result.exit_code == 2
    assert "set TRANSPORT_MATTERS_DATABASE_URL" in result.output


def test_channel_promote_rejects_non_preview_to_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(channel_cmd, "run_install_local", lambda root: calls.append(root))

    result = runner.invoke(main, ["channel", "promote", "stable", "preview"])

    assert result.exit_code == 2
    assert "only preview stable is supported" in result.output
    assert calls == []


def test_channel_promote_preview_to_stable_runs_install_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Path] = []

    def fail_if_promote_touches_database(*args: object, **kwargs: object) -> None:
        raise AssertionError("promote must not touch channel data")

    def fake_run_install_local(root: Path) -> None:
        calls.append(root)

    monkeypatch.setattr(channel_cmd, "ensure_channel_database", fail_if_promote_touches_database)
    monkeypatch.setattr(channel_cmd, "run_install_local", fake_run_install_local)

    result = runner.invoke(main, ["channel", "promote", "preview", "stable"])

    assert result.exit_code == 0, result.output
    assert calls == [channel_cmd.repo_root()]
    assert "transport-matters desktop --channel stable" in result.output
