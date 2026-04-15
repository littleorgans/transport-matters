"""Tests for ``manicure start``.

The bulk of the CLI surface lives here: ``start`` orchestrates port
allocation, workspace locking, manifest writing, system-prompt
injection, and finally hands off to ``_run_children``. Tests either
short-circuit through ``--print-command`` or replace ``_run_children``
with the ``spy_run_children`` fixture so no real fork happens.

Sections (preserved from the original ``test_cli.py``):
  print-command, pass-through, validation/failure paths,
  ``_run_children`` wiring, addon discovery, workspace lock + manifest.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

from typer.testing import CliRunner

from manicure.cli import (
    WorkspaceLock,
    main,
    manifest_write,
    workspace_id,
    workspace_root,
)
from manicure.workspace import workspace_storage

from ._helpers import _sample_manifest, _which_all, _which_by_name, _which_none

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()


# --------------------------------------------------------------------------- #
# start: --print-command                                                      #
# --------------------------------------------------------------------------- #


def test_start_print_command_does_not_spawn(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """``--print-command`` must short-circuit before we spawn anything."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["start", "--print-command"])
    assert result.exit_code == 0
    # Should echo the mitmdump invocation.
    assert "mitmdump" in result.stdout
    assert "reverse:https://api.anthropic.com" in result.stdout
    assert "--listen-port" in result.stdout
    spy_run_children.assert_not_called()


def test_start_print_command_includes_claude_invocation(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """With claude on PATH, both child invocations are printed."""
    monkeypatch.setattr(
        "manicure.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    # Suppress system-prompt injection so the test pins the bare argv
    # shape; system-prompt behaviour has its own tests.
    result = runner.invoke(main, ["start", "--no-system-prompt", "--print-command"])
    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    # Last two meaningful lines are the mitmdump and claude argvs.
    assert any("/bin/mitmdump" in line for line in lines)
    assert any(line == "/bin/claude" for line in lines)
    spy_run_children.assert_not_called()


def test_start_print_command_no_claude_omits_claude(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """``--no-claude`` skips the claude resolution and prints only mitmdump."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all("/bin/mitmdump"))
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["start", "--no-claude", "--print-command"])
    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert any("mitmdump" in line for line in lines)
    assert not any(line.endswith("claude") and "mitmdump" not in line for line in lines)
    spy_run_children.assert_not_called()


def test_start_print_command_respects_port_and_upstream(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        [
            "start",
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
    spy_run_children: MagicMock,
    tmp_path: Path,
) -> None:
    """``--claude-bin PATH`` bypasses PATH resolution."""
    monkeypatch.setattr(
        "manicure.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),  # claude -> None
    )
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    fake_claude = tmp_path / "my-claude"
    fake_claude.write_text("#!/bin/sh\nexec echo hi\n")
    fake_claude.chmod(0o755)

    result = runner.invoke(
        main,
        ["start", "--claude-bin", str(fake_claude), "--print-command"],
    )
    assert result.exit_code == 0
    assert str(fake_claude) in result.stdout


# --------------------------------------------------------------------------- #
# start: pass-through args after `--`                                         #
# --------------------------------------------------------------------------- #


def test_start_print_command_includes_passthrough(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Args after ``--`` must appear on the printed claude line."""
    monkeypatch.setattr(
        "manicure.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        ["start", "--print-command", "--", "--model", "sonnet", "--resume"],
    )
    assert result.exit_code == 0, result.output
    # The claude argv line starts with the resolved binary path; the
    # pass-through tokens must appear after it, in order.
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
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

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
        "manicure.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

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
        "manicure.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

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
    # Pass-through tokens appear AFTER the binary path, in order.
    assert claude_line.startswith("/bin/claude ")
    assert "--model sonnet" in claude_line


def test_start_passthrough_forwards_to_run_children(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Without ``--print-command``, the tail reaches ``_run_children`` verbatim."""
    monkeypatch.setattr(
        "manicure.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    result = runner.invoke(
        main, ["start", "--no-system-prompt", "--", "-p", "hello world"]
    )
    assert result.exit_code == 0, result.output
    kwargs = spy_run_children.call_args.kwargs
    assert kwargs["claude_argv"] == ["/bin/claude", "-p", "hello world"]


# --------------------------------------------------------------------------- #
# start: validation / failure paths                                           #
# --------------------------------------------------------------------------- #


def test_start_refuses_when_proxy_port_is_busy(
    tmp_storage: Path,
    busy_port: int,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    # Force the port check to flag exactly the proxy port.
    monkeypatch.setattr(
        "manicure.cli._port_in_use",
        lambda p: p == busy_port,
    )

    result = runner.invoke(
        main,
        [
            "start",
            "--proxy-port",
            str(busy_port),
            "--web-port",
            "8788",
            "--print-command",
        ],
    )
    assert result.exit_code == 2
    assert "already in use" in result.output
    spy_run_children.assert_not_called()


def test_start_refuses_when_mitmdump_missing(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", _which_none())

    result = runner.invoke(main, ["start", "--print-command"])
    assert result.exit_code == 2
    assert "`mitmdump` was not found" in result.output
    assert "uv tool install --force manicure" in result.output
    spy_run_children.assert_not_called()


def test_start_refuses_when_claude_missing(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """No claude on PATH, no --claude-bin, no --no-claude → exit 2 with hint."""
    monkeypatch.setattr(
        "manicure.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),  # claude -> None
    )
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["start", "--print-command"])
    assert result.exit_code == 2
    assert "`claude` was not found" in result.output
    assert "npm install -g @anthropic-ai/claude-code" in result.output
    assert "--no-claude" in result.output
    spy_run_children.assert_not_called()


def test_start_no_claude_works_when_claude_absent(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """``--no-claude`` skips the claude-missing error."""
    monkeypatch.setattr(
        "manicure.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump"}),  # claude -> None
    )
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["start", "--no-claude", "--print-command"])
    assert result.exit_code == 0


def test_start_rejects_malformed_upstream_url(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Upstream URL must have both a scheme and hostname."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        ["start", "--upstream", "not-a-url", "--print-command"],
    )
    assert result.exit_code == 2
    assert "invalid upstream URL" in result.output
    spy_run_children.assert_not_called()


def test_start_rejects_upstream_without_scheme(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    result = runner.invoke(
        main,
        ["start", "--upstream", "api.anthropic.com", "--print-command"],
    )
    assert result.exit_code == 2
    assert "invalid upstream URL" in result.output
    spy_run_children.assert_not_called()


def test_start_rejects_missing_directory(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Non-existent positional directory is rejected by click before we run."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    missing = tmp_path / "does-not-exist"
    result = runner.invoke(main, ["start", str(missing), "--print-command"])
    # Click/Typer validates `file_okay=False, dir_okay=True` at the CLI
    # layer; our body only runs for values that pass. Either click
    # rejects it (exit 2, "does not exist" in output) or our body does
    # — we accept either.
    assert result.exit_code == 2
    assert (
        "does not exist" in result.output.lower() or "does-not-exist" in result.output
    )
    spy_run_children.assert_not_called()


def test_start_accepts_directory_argument(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """A valid directory passes validation and reaches print-command."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["start", str(workdir), "--print-command"])
    assert result.exit_code == 0


def test_start_does_not_pollute_os_environ(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """The start command builds a child_env dict instead of mutating os.environ."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    # Ensure these keys are absent before start
    monkeypatch.delenv("MANICURE_WEB_PORT", raising=False)
    monkeypatch.delenv("MANICURE_PROXY_PORT", raising=False)

    result = runner.invoke(
        main,
        [
            "start",
            "--proxy-port",
            "9500",
            "--web-port",
            "9501",
            "--print-command",
        ],
    )
    assert result.exit_code == 0
    # --print-command exits before spawning, so os.environ should not
    # contain the child ports that start prepares.
    import os

    assert os.environ.get("MANICURE_WEB_PORT") != "9501"
    assert os.environ.get("MANICURE_PROXY_PORT") != "9500"


def test_start_fails_when_addon_missing(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    fake_traversable = MagicMock()
    fake_traversable.is_file.return_value = False

    def _fake_files(_pkg: str) -> Any:
        root = MagicMock()
        root.__truediv__.return_value = fake_traversable
        return root

    monkeypatch.setattr("manicure.cli.files", _fake_files)

    result = runner.invoke(main, ["start", "--print-command"])
    assert result.exit_code == 2
    assert "could not locate the manicure mitmproxy addon" in result.output
    spy_run_children.assert_not_called()


# --------------------------------------------------------------------------- #
# start: _run_children wiring                                                 #
# --------------------------------------------------------------------------- #


def test_start_calls_run_children_with_claude_env(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """When not using --print-command, the spawn helper gets a claude env
    with ANTHROPIC_BASE_URL pointed at the proxy."""
    monkeypatch.setattr(
        "manicure.cli.shutil.which",
        _which_by_name({"mitmdump": "/bin/mitmdump", "claude": "/bin/claude"}),
    )
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(
        main,
        ["start", str(workdir), "--no-system-prompt", "--proxy-port", "9900"],
    )
    assert result.exit_code == 0, result.output
    spy_run_children.assert_called_once()
    kwargs = spy_run_children.call_args.kwargs
    assert kwargs["claude_argv"] == ["/bin/claude"]
    assert kwargs["claude_env"]["ANTHROPIC_BASE_URL"] == "http://localhost:9900"
    assert kwargs["claude_cwd"] == workdir
    assert kwargs["proxy_port"] == 9900
    # mitmdump gets its normal invocation; the supervisor will add the
    # PYTHONUNBUFFERED env wrapper.
    assert kwargs["mitmdump_argv"][0] == "/bin/mitmdump"
    assert "reverse:https://api.anthropic.com" in kwargs["mitmdump_argv"]


def test_start_no_claude_passes_none_claude_argv(
    tmp_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    result = runner.invoke(main, ["start", "--no-claude"])
    assert result.exit_code == 0, result.output
    kwargs = spy_run_children.call_args.kwargs
    assert kwargs["claude_argv"] is None
    assert kwargs["claude_env"] is None


# --------------------------------------------------------------------------- #
# start: workspace lock + manifest                                            #
# --------------------------------------------------------------------------- #


def test_start_fails_fast_when_workspace_locked(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Second ``start`` in the same CWD must exit 2 and surface the live
    instance's PID + ports from the manifest."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    ws_root = workspace_root(workdir)
    ws_root.mkdir(parents=True, exist_ok=True)
    manifest_write(
        ws_root / "manifest.json",
        _sample_manifest(
            workdir=workdir, storage=tmp_storage, pid=99999, proxy_port=4545
        ),
    )

    # Hold the lock to simulate a concurrent live instance.
    with WorkspaceLock(ws_root):
        result = runner.invoke(main, ["start", str(workdir)])

    assert result.exit_code == 2
    assert "already live" in result.output
    assert "99999" in result.output
    assert "4545" in result.output
    # web_port default on _sample_manifest is 8788 — spec says "PID + ports".
    assert "8788" in result.output
    spy_run_children.assert_not_called()


def test_start_contention_message_falls_back_when_manifest_missing(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Lock held but no sibling manifest: still exit 2 with a pointer
    at the lock path (don't blow up on ``manifest_read -> None``)."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    ws_root = workspace_root(workdir)

    with WorkspaceLock(ws_root):
        result = runner.invoke(main, ["start", str(workdir)])

    assert result.exit_code == 2
    assert "lock" in result.output.lower()
    spy_run_children.assert_not_called()


def test_start_writes_manifest_visible_to_children(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While ``_run_children`` is running the manifest must exist on disk
    with the right fields — ``manicure list`` in a sibling process must
    be able to see us."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    captured: dict[str, Any] = {}

    def _fake_run_children(**kwargs: Any) -> None:
        cwd = kwargs["claude_cwd"]
        manifest_path = workspace_root(cwd) / "manifest.json"
        captured["exists_mid_run"] = manifest_path.exists()
        # Read it raw to verify the on-disk shape without tying the test
        # to the Manifest dataclass version.
        captured["raw"] = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Patched at the runner-module call site — the retry harness in
    # ``_run_with_retry`` resolves ``_run_children`` against runner's
    # own namespace, so the package-level re-export does not intercept.
    monkeypatch.setattr("manicure.cli.runner._run_children", _fake_run_children)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(
        main, ["start", str(workdir), "--proxy-port", "9123", "--web-port", "9124"]
    )
    assert result.exit_code == 0, result.output
    assert captured["exists_mid_run"] is True
    raw = captured["raw"]
    assert raw["cwd"] == str(workdir)
    assert raw["proxy_port"] == 9123
    assert raw["web_port"] == 9124
    assert raw["pid"] > 0
    assert raw["slug"] == workspace_id(workdir).slug
    assert raw["hash"] == workspace_id(workdir).hash


def test_start_releases_lock_on_normal_exit(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """After a successful ``start``, the lock must release — a second
    ``start`` in the same CWD must succeed."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result_a = runner.invoke(main, ["start", str(workdir)])
    assert result_a.exit_code == 0, result_a.output
    # Manifest removed on clean exit.
    assert not (workspace_root(workdir) / "manifest.json").exists()
    # Lock re-acquirable.
    with WorkspaceLock(workspace_root(workdir)):
        pass
    # Second start succeeds.
    result_b = runner.invoke(main, ["start", str(workdir)])
    assert result_b.exit_code == 0, result_b.output
    assert spy_run_children.call_count == 2


def test_start_different_cwds_coexist(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Two ``start``s in different CWDs must not contend on the lock."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    dir_a = tmp_path / "a"
    dir_a.mkdir()
    dir_b = tmp_path / "b"
    dir_b.mkdir()

    # Hold the lock for dir_a; start in dir_b must still succeed.
    with WorkspaceLock(workspace_root(dir_a)):
        result = runner.invoke(main, ["start", str(dir_b)])
    assert result.exit_code == 0, result.output


# --------------------------------------------------------------------------- #
# start: per-workspace storage (Phase 3)                                      #
# --------------------------------------------------------------------------- #


def test_start_defaults_storage_to_workspace_root(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Without ``--storage-dir`` the child env carries the workspace root.

    This is the Phase 3 fix for the shared-storage bug — each CWD now
    resolves to its own ``~/.manicure/workspaces/{slug}/{hash}/`` dir.
    """
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)
    # Drop the legacy MANICURE_STORAGE_DIR override (``tmp_storage``
    # sets it pre-Phase 3); we want to exercise the per-workspace
    # default path, not the explicit override.
    monkeypatch.delenv("MANICURE_STORAGE_DIR", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["start", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    spy_run_children.assert_called_once()
    kwargs = spy_run_children.call_args.kwargs
    expected = workspace_storage(workdir)
    # The child env (mitmdump_env / claude_env) both inherit MANICURE_
    # storage from the resolved root. Assert against claude_env since
    # `--no-claude` is not set here.
    assert kwargs["claude_env"]["MANICURE_STORAGE_DIR"] == str(expected)


def test_start_explicit_storage_dir_overrides_workspace_root(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """``--storage-dir`` still wins over the per-workspace default."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    override = tmp_path / "override"
    override.mkdir()
    result = runner.invoke(
        main,
        [
            "start",
            str(workdir),
            "--storage-dir",
            str(override),
            "--no-system-prompt",
        ],
    )
    assert result.exit_code == 0, result.output
    kwargs = spy_run_children.call_args.kwargs
    assert kwargs["claude_env"]["MANICURE_STORAGE_DIR"] == str(override)


def test_start_flows_working_dir_into_manicure_cwd_env(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """``MANICURE_CWD`` rides on the child env so the API-side meta
    endpoint returns the user's launch directory instead of whatever
    cwd the mitmdump process inherits.
    """
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)
    monkeypatch.delenv("MANICURE_CWD", raising=False)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["start", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    kwargs = spy_run_children.call_args.kwargs
    assert kwargs["claude_env"]["MANICURE_CWD"] == str(workdir)
    assert kwargs["mitmdump_env"]["MANICURE_CWD"] == str(workdir)


def test_start_writes_workspace_storage_into_manifest(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manifest records the per-workspace path so ``list`` surfaces it."""
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)
    monkeypatch.delenv("MANICURE_STORAGE_DIR", raising=False)

    captured: dict[str, Any] = {}

    def _fake_run_children(**kwargs: Any) -> None:
        cwd = kwargs["claude_cwd"]
        manifest_path = workspace_root(cwd) / "manifest.json"
        captured["raw"] = json.loads(manifest_path.read_text(encoding="utf-8"))

    monkeypatch.setattr("manicure.cli.runner._run_children", _fake_run_children)

    workdir = tmp_path / "project"
    workdir.mkdir()
    result = runner.invoke(main, ["start", str(workdir), "--no-system-prompt"])
    assert result.exit_code == 0, result.output
    assert captured["raw"]["storage_dir"] == str(workspace_storage(workdir))


def test_start_different_cwds_get_disjoint_storage(
    tmp_storage: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    spy_run_children: MagicMock,
) -> None:
    """Two starts in different CWDs must resolve to different storage roots.

    Acceptance criterion (spec line 169) — the triggering bug.
    """
    monkeypatch.setattr("manicure.cli.shutil.which", _which_all())
    monkeypatch.setattr("manicure.cli._port_in_use", lambda _: False)
    monkeypatch.delenv("MANICURE_STORAGE_DIR", raising=False)

    dir_a = tmp_path / "a"
    dir_a.mkdir()
    dir_b = tmp_path / "b"
    dir_b.mkdir()

    result_a = runner.invoke(main, ["start", str(dir_a), "--no-system-prompt"])
    assert result_a.exit_code == 0, result_a.output
    env_a = spy_run_children.call_args_list[0].kwargs["claude_env"]

    result_b = runner.invoke(main, ["start", str(dir_b), "--no-system-prompt"])
    assert result_b.exit_code == 0, result_b.output
    env_b = spy_run_children.call_args_list[1].kwargs["claude_env"]

    assert env_a["MANICURE_STORAGE_DIR"] != env_b["MANICURE_STORAGE_DIR"]
    assert env_a["MANICURE_STORAGE_DIR"] == str(workspace_storage(dir_a))
    assert env_b["MANICURE_STORAGE_DIR"] == str(workspace_storage(dir_b))


# Phase 2 acceptance tests (port allocation, system-prompt injection)
# live in ``test_start_acceptance.py`` to keep this file under the
# per-file LOC budget.
