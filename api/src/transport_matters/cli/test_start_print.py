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


def test_start_print_command_does_not_spawn(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """``--print-command`` must short-circuit before we spawn anything."""
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--print-command"])
    assert result.exit_code == 0
    assert "mitmdump" in result.stdout
    assert "reverse:https://api.anthropic.com" in result.stdout
    assert "--listen-port" in result.stdout
    spy_run_client_children.assert_not_called()


def test_start_prefers_same_environment_mitmdump(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """Use the mitmdump binary from the active environment before PATH."""

    def fake_which(name: str, path: str | None = None) -> str | None:
        if name == "mitmdump" and path == "/tool/bin":
            return "/tool/bin/mitmdump"
        if name == "mitmdump":
            return "/usr/local/bin/mitmdump"
        if name == "claude":
            return "/bin/claude"
        return None

    monkeypatch.setattr(
        "transport_matters.cli.sysconfig.get_path", lambda name: "/tool/bin"
    )
    monkeypatch.setattr("transport_matters.cli.shutil.which", fake_which)
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--no-system-prompt", "--print-command"])
    assert result.exit_code == 0
    assert "/tool/bin/mitmdump" in result.stdout
    assert "/usr/local/bin/mitmdump" not in result.stdout
    spy_run_client_children.assert_not_called()


def test_start_print_command_includes_claude_invocation(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """With claude on PATH, both child invocations are printed."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--no-system-prompt", "--print-command"])
    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert any("/bin/mitmdump" in line for line in lines)
    assert any(line == "/bin/claude" for line in lines)
    spy_run_client_children.assert_not_called()


def test_start_print_command_no_claude_omits_claude(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    """``--no-claude`` skips the claude resolution and prints only mitmdump."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which", _which_all("/bin/mitmdump")
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["claude", "--no-claude", "--print-command"])
    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert any("mitmdump" in line for line in lines)
    assert not any(line.endswith("claude") and "mitmdump" not in line for line in lines)
    spy_run_client_children.assert_not_called()


def test_start_print_command_respects_port_and_upstream(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
) -> None:
    monkeypatch.setattr("transport_matters.cli.shutil.which", _which_all())
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        [
            "claude",
            "--proxy-port",
            "9000",
            "--web-port",
            "9001",
            "--upstream",
            "https://example.test",
            "--print-command",
        ],
    )
    assert result.exit_code == 0
    assert "9000" in result.stdout
    assert "reverse:https://example.test" in result.stdout


def test_start_uses_claude_bin_override(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_client_children: MagicMock,
    tmp_path: Path,
) -> None:
    """``--claude-bin PATH`` bypasses PATH resolution."""
    monkeypatch.setattr(
        "transport_matters.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),
    )
    monkeypatch.setattr("transport_matters.cli._port_in_use", lambda _: False)

    fake_claude = tmp_path / "my-claude"
    fake_claude.write_text("#!/bin/sh\nexec echo hi\n")
    fake_claude.chmod(0o755)

    result = runner.invoke(
        main,
        ["claude", "--claude-bin", str(fake_claude), "--print-command"],
    )
    assert result.exit_code == 0
    assert str(fake_claude) in result.stdout
