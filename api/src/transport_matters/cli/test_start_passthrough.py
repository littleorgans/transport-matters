from __future__ import annotations

from typing import TYPE_CHECKING

from typer.testing import CliRunner

from transport_matters.cli import main

from ._helpers import _which_all, _which_by_name

if TYPE_CHECKING:
    from pathlib import Path
    from unittest.mock import MagicMock

    import pytest

runner = CliRunner()


def test_start_print_command_includes_passthrough(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Args after ``--`` must appear on the printed claude line."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        ["start", "--print-command", "--", "--model", "sonnet", "--resume"],
    )
    assert result.exit_code == 0, result.output
    claude_line = next(
        line for line in result.stdout.splitlines() if line.startswith("/bin/claude")
    )
    assert "--model" in claude_line
    assert "sonnet" in claude_line
    assert "--resume" in claude_line
    spy_run_children.assert_not_called()


def test_start_no_claude_plus_passthrough_fails(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """``--no-claude`` + pass-through is nonsensical and exits 2."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["start", "--no-claude", "--", "--model", "sonnet"])
    assert result.exit_code == 2
    assert "--no-claude" in result.output
    spy_run_children.assert_not_called()


def test_start_empty_double_dash_is_noop(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """``manicure start --`` with nothing after it must behave like no ``--``."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["start", "--no-system-prompt", "--"])
    assert result.exit_code == 0, result.output
    spy_run_children.assert_called_once()
    assert spy_run_children.call_args.kwargs["claude_argv"] == ["/bin/claude"]


def test_start_dir_plus_passthrough(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Positional directory + pass-through: both survive."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(
        main,
        ["start", str(workdir), "--print-command", "--", "--model", "sonnet"],
    )
    assert result.exit_code == 0, result.output
    claude_line = next(
        line for line in result.stdout.splitlines() if line.startswith("/bin/claude")
    )
    assert claude_line.startswith("/bin/claude ")
    assert "--model sonnet" in claude_line


def test_start_passthrough_forwards_to_run_children(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Without ``--print-command``, the tail reaches ``_run_children`` verbatim."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(
        main, ["start", "--no-system-prompt", "--", "-p", "hello world"]
    )
    assert result.exit_code == 0, result.output
    kwargs = spy_run_children.call_args.kwargs
    assert kwargs["claude_argv"] == ["/bin/claude", "-p", "hello world"]
