"""Tests for the root help surface and Claude command help.

Per-command help (``doctor``, ``paths``, ``list``) lives next to its
command's behaviour tests in the matching ``test_<cmd>.py`` module.
"""

from typer.testing import CliRunner

from transport_matters.cli import main

from ._helpers import _plain

runner = CliRunner()


def test_root_help_includes_quick_start() -> None:
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "Transport Matters" in output
    assert "transport-matters claude" in output
    assert "manicure claude" not in output
    assert "Quick start" in output
    assert "Commands" in output
    assert "claude" in output
    assert "  start     " not in output
    assert "manicure start" not in output


def test_root_help_includes_environment() -> None:
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    old_prefix = "MANI" + "CURE_"
    assert "TRANSPORT_MATTERS_PROXY_PORT" in output
    assert "TRANSPORT_MATTERS_STORAGE_DIR" in output
    assert "addon/paths/doctor data dir" in output
    assert "launches use per-run storage" in output
    assert f"{old_prefix}PROXY_PORT" not in output
    assert f"{old_prefix}STORAGE_DIR" not in output


def test_root_help_lists_list_command() -> None:
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "list" in output
    assert "List live Transport Matters instances" in output


def test_root_help_lists_codex_command() -> None:
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "codex" in output
    assert "Run proxy + Codex together" in output


def test_claude_help_includes_examples() -> None:
    result = runner.invoke(main, ["claude", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "Examples" in output
    assert "--work-dir" in output
    assert "--agent-home-dir" in output
    assert "--proxy-port" in output


def test_start_alias_is_removed() -> None:
    result = runner.invoke(main, ["start", "--help"])
    assert result.exit_code != 0
    assert "No such command" in result.output


def test_codex_help_includes_proxy_env() -> None:
    result = runner.invoke(main, ["codex", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "HTTP_PROXY" in output
    assert "HTTPS_PROXY" in output
    assert "CODEX_CA_CERTIFICATE" in output
    assert "--work-dir" in output
    assert "--agent-home-dir" in output
    assert "--codex-bin" in output
