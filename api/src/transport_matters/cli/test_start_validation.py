from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from transport_matters.cli import main

from ._helpers import _which_all, _which_by_name, _which_none

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import MagicMock

    import pytest

runner = CliRunner()


def test_start_refuses_when_proxy_port_is_busy(
    tmp_storage: Path,
    busy_port: int,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda p: p == busy_port)

    result = runner.invoke(
        main,
        [
            "claude",
            "--proxy-port",
            str(busy_port),
            "--web-port",
            "8788",
            "--print-command",
        ],
    )
    assert result.exit_code == 2
    assert "already in use" in result.output
    spy_run_client_children.assert_not_called()


def test_start_refuses_when_mitmdump_missing(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_none())

    result = runner.invoke(main, ["claude", "--print-command"])
    assert result.exit_code == 2
    assert "`mitmdump` was not found" in result.output
    assert "uv tool install --force transport-matters" in result.output
    spy_run_client_children.assert_not_called()


def test_start_refuses_when_claude_missing(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """No claude on PATH, no --claude-bin, no --no-claude → exit 2 with hint."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--print-command"])
    assert result.exit_code == 2
    assert "`claude` was not found" in result.output
    assert "npm install -g @anthropic-ai/claude-code" in result.output
    assert "--no-claude" in result.output
    spy_run_client_children.assert_not_called()


def test_start_no_claude_works_when_claude_absent(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """``--no-claude`` skips the claude-missing error."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--no-claude", "--print-command"])
    assert result.exit_code == 0


def test_start_rejects_malformed_upstream_url(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Upstream URL must have both a scheme and hostname."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        ["claude", "--upstream", "not-a-url", "--print-command"],
    )
    assert result.exit_code == 2
    assert "invalid upstream URL" in result.output
    spy_run_client_children.assert_not_called()


def test_start_rejects_upstream_without_scheme(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        ["claude", "--upstream", "api.anthropic.com", "--print-command"],
    )
    assert result.exit_code == 2
    assert "invalid upstream URL" in result.output
    spy_run_client_children.assert_not_called()


def test_start_rejects_missing_directory(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Non-existent positional directory is rejected by click before we run."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    missing = tmp_path / "does-not-exist"
    result = runner.invoke(main, ["claude", str(missing), "--print-command"])
    assert result.exit_code == 2
    assert (
        "does not exist" in result.output.lower() or "does-not-exist" in result.output
    )
    spy_run_client_children.assert_not_called()
