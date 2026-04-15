"""Tests for the root help surface and ``manicure start --help``.

Per-command help (``doctor``, ``paths``, ``list``) lives next to its
command's behaviour tests in the matching ``test_<cmd>.py`` module.
"""

from __future__ import annotations

from typer.testing import CliRunner

from manicure.cli import main

from ._helpers import _plain

runner = CliRunner()


def test_root_help_includes_quick_start() -> None:
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "manicure" in output
    assert "Quick start" in output
    assert "Commands" in output
    assert "start" in output


def test_root_help_includes_environment() -> None:
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "MANICURE_PROXY_PORT" in output
    assert "MANICURE_STORAGE_DIR" in output


def test_root_help_lists_list_command() -> None:
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "list" in output
    assert "List live manicure instances" in output


def test_start_help_includes_examples() -> None:
    result = runner.invoke(main, ["start", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "Examples" in output
    assert "--proxy-port" in output
