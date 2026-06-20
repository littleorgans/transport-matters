"""Tests for the shared launch-path session-store preflight (fail-fast)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import typer
from typer.testing import CliRunner

from transport_matters import config, env_keys
from transport_matters.cli import launch_runtime, main
from transport_matters.session_store_preflight import check_session_store

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from transport_matters.channel import ChannelSpec
    from transport_matters.session.testing import TestDb

runner = CliRunner()


def test_check_session_store_reports_missing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRANSPORT_MATTERS_HOME", str(tmp_path))  # empty: no settings.toml
    monkeypatch.delenv("TRANSPORT_MATTERS_DATABASE_URL", raising=False)
    config.get_settings.cache_clear()

    msg = check_session_store()

    assert msg is not None
    assert "not configured" in msg


def test_check_session_store_reports_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRANSPORT_MATTERS_HOME", str(tmp_path))
    monkeypatch.setenv("TRANSPORT_MATTERS_DATABASE_URL", "postgresql://u:p@127.0.0.1:1/none")
    config.get_settings.cache_clear()

    msg = check_session_store()

    assert msg is not None
    assert "reach" in msg.lower()


def test_preflight_scaffolds_and_exits_when_store_unusable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRANSPORT_MATTERS_HOME", str(tmp_path))
    monkeypatch.setattr(launch_runtime, "check_session_store", lambda: "boom")

    with pytest.raises(typer.Exit) as exc:
        launch_runtime.preflight_session_store_or_exit()

    assert exc.value.exit_code == 2
    # First-run scaffold created the starter settings.toml from the packaged example.
    assert (tmp_path / "settings.toml").exists()


def test_preflight_returns_when_store_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch_runtime, "ensure_settings_scaffold", lambda: None)
    monkeypatch.setattr(launch_runtime, "check_session_store", lambda: None)

    launch_runtime.preflight_session_store_or_exit()  # must not raise


def test_channel_ensure_db_makes_launch_preflight_pass(
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

    result = runner.invoke(main, ["channel", "ensure-db", "tmp"])

    assert result.exit_code == 0, result.output
    launch_runtime.preflight_session_store_or_exit()
