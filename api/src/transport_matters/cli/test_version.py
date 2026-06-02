"""Tests for ``transport-matters version`` and ``transport-matters --version``."""

from typer.testing import CliRunner

from transport_matters import __version__
from transport_matters.cli import main

runner = CliRunner()


def test_version_command_prints_version() -> None:
    result = runner.invoke(main, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_version_flag_on_root_prints_version() -> None:
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("transport-matters ")
    assert __version__ in result.stdout


def test_version_short_flag_prints_version() -> None:
    result = runner.invoke(main, ["-V"])
    assert result.exit_code == 0
    assert result.stdout.startswith("transport-matters ")
    assert __version__ in result.stdout
