"""Tests for ``manicure doctor``.

The doctor body lives in ``cli/diagnose.py``. ``shutil.which`` resolves
through ``manicure.cli.shutil.which`` (re-exported at package scope) so
existing patches keep working; ``_port_in_use`` is rebound by name in
``diagnose`` so tests must patch it at ``manicure.cli.diagnose``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from manicure.cli import WorkspaceLock, main, workspace_root

from ._helpers import _plain, _which_all, _which_none

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()


def test_doctor_happy_path(
    tmp_storage: Path, monkeypatch: pytest.MonkeyPatch, free_port: int
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    # Force the two default ports to appear free by patching _port_in_use
    # at the module that actually consumes it (cli.diagnose, not cli).
    monkeypatch.setattr("manicure.cli.diagnose._port_in_use", lambda _: False)
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 0
    assert "all checks passed" in result.stdout
    assert "ok    python" in result.stdout
    assert "ok    mitmdump" in result.stdout
    assert "ok    addon" in result.stdout
    assert "ok    storage" in result.stdout


def test_doctor_reports_missing_mitmdump(
    tmp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", _which_none())
    monkeypatch.setattr("manicure.cli.diagnose._port_in_use", lambda _: False)
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 1
    assert "fail  mitmdump" in result.output
    assert "uv tool install --force manicure" in result.output
    assert "check(s) failed" in result.output


def test_doctor_warns_when_ports_are_busy(
    tmp_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli.diagnose._port_in_use", lambda _: True)
    result = runner.invoke(main, ["doctor"])
    # Port warnings are not fatal, so exit code is still 0.
    assert result.exit_code == 0
    assert "warn  proxy port" in result.stdout
    assert "warn  web port" in result.stdout


def test_doctor_fails_when_storage_unwritable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Point storage at a file (not a directory) — mkdir will succeed
    # creating parents but the write probe will fail with OSError.
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir")
    monkeypatch.setenv("MANICURE_STORAGE_DIR", str(blocker))
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli.diagnose._port_in_use", lambda _: False)
    from manicure import config

    config.get_settings.cache_clear()
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 1
    assert "fail  storage" in result.output


def test_doctor_works_with_live_lock_in_same_cwd(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``doctor`` is read-only and must not touch the workspace lock."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli.diagnose._port_in_use", lambda _: False)
    monkeypatch.chdir(tmp_path)
    with WorkspaceLock(workspace_root(tmp_path)):
        result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 0
    assert "all checks passed" in result.stdout


def test_doctor_help_renders() -> None:
    result = runner.invoke(main, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "diagnose" in _plain(result.output).lower()
