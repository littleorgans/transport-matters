"""Tests for the shared launch-path session-store preflight (fail-fast)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import typer

from transport_matters import config
from transport_matters.cli import launch_runtime
from transport_matters.session_store_preflight import check_session_store

if TYPE_CHECKING:
    from pathlib import Path


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
