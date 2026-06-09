"""Tests for ``transport-matters desktop``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

from click.core import ParameterSource
from typer.testing import CliRunner

import transport_matters.cli as cli
from transport_matters import env_keys
from transport_matters.cli import main
from transport_matters.cli.desktop_cmd import (
    DesktopLaunchPlan,
    ElectronLaunch,
    prepare_desktop_launch,
)

from ._helpers import _plain

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

runner = CliRunner()


class _DefaultOptionContext:
    def get_parameter_source(self, _name: str) -> ParameterSource:
        return ParameterSource.DEFAULT


def test_desktop_help_lists_canvas_and_agent_options() -> None:
    result = runner.invoke(main, ["desktop", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--agent" in output
    assert "--work-dir" in output
    assert "--agent-home-dir" in output
    assert "--claude-bin" in output
    assert "--codex-bin" in output
    assert "--force-http-fallback" in output
    assert "Electron canvas" in output


def test_desktop_rejects_codex_options_for_default_claude(tmp_path: Path) -> None:
    codex_bin = tmp_path / "codex"
    codex_bin.write_text("#!/bin/sh\n")

    result = runner.invoke(main, ["desktop", "--codex-bin", str(codex_bin)])

    assert result.exit_code == 2
    assert "--codex-bin only valid with --agent codex" in result.output


def test_desktop_rejects_claude_options_for_codex() -> None:
    result = runner.invoke(main, ["desktop", "--agent", "codex", "--no-system-prompt"])

    assert result.exit_code == 2
    assert "--no-system-prompt only valid with --agent claude" in result.output


def test_desktop_ignores_ambient_cross_agent_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    def fake_run_codex(**kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(cli, "run_codex", fake_run_codex)

    result = runner.invoke(
        main,
        ["desktop", "--agent", "codex", "--print-command"],
        env={env_keys.UPSTREAM_URL: "http://ambient.example"},
    )

    assert result.exit_code == 0
    assert calls["print_command"] is True


def test_desktop_command_forwards_to_codex_without_preallocating_ports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, Any] = {}

    def fake_prepare_desktop_launch(**kwargs: Any) -> DesktopLaunchPlan:
        return DesktopLaunchPlan(
            agent=kwargs["agent"],
            run_client_with_retry=kwargs["base_run_client_with_retry"],
        )

    def fake_run_codex(**kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(cli, "prepare_desktop_launch", fake_prepare_desktop_launch)
    monkeypatch.setattr(cli, "run_codex", fake_run_codex)
    monkeypatch.setattr(cli, "allocate_port_pair", lambda: (_ for _ in ()).throw(AssertionError))

    result = runner.invoke(
        main,
        ["desktop", "--agent", "codex", "--work-dir", str(tmp_path), "--", "exec", "hello"],
    )

    assert result.exit_code == 0
    assert calls["directory"] == tmp_path
    assert calls["codex_passthrough"] == ["exec", "hello"]
    assert calls["default_client_passthrough"] == ("exec", "hello")
    assert calls["proxy_port"] is None
    assert calls["web_port"] is None


def test_desktop_command_forwards_default_passthrough_to_claude_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, Any] = {}

    def fake_prepare_desktop_launch(**kwargs: Any) -> DesktopLaunchPlan:
        return DesktopLaunchPlan(
            agent=kwargs["agent"],
            run_client_with_retry=kwargs["base_run_client_with_retry"],
        )

    def fake_run_start(**kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(cli, "prepare_desktop_launch", fake_prepare_desktop_launch)
    monkeypatch.setattr(cli, "run_start", fake_run_start)

    result = runner.invoke(
        main,
        [
            "desktop",
            "--work-dir",
            str(tmp_path),
            "--",
            "--dangerously-skip-permissions",
            "--model",
            "sonnet",
        ],
    )

    assert result.exit_code == 0
    assert calls["claude_passthrough"] == [
        "--dangerously-skip-permissions",
        "--model",
        "sonnet",
    ]
    assert calls["default_client_passthrough"] == (
        "--dangerously-skip-permissions",
        "--model",
        "sonnet",
    )


def test_desktop_startup_hook_emits_json_and_spawns_electron(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    electron = ElectronLaunch(argv=("/bin/electron", "/app"), cwd=tmp_path)
    spawned: list[tuple[ElectronLaunch, dict[str, Any]]] = []

    def fake_run_client_with_retry(**kwargs: Any) -> None:
        kwargs["on_backend_ready"](
            {
                env_keys.CWD: str(tmp_path),
                env_keys.AGENT_HOME_DIR: str(tmp_path / "agent-home"),
                env_keys.RUN_ID: "run-001",
            },
            tmp_path / "storage",
            None,
            9900,
            9901,
        )

    plan = prepare_desktop_launch(
        ctx=_DefaultOptionContext(),  # type: ignore[arg-type]
        agent="claude",
        base_run_client_with_retry=fake_run_client_with_retry,
        resolve_electron_launch_func=lambda: electron,
        spawn_electron_func=lambda launch, event: spawned.append((launch, event)),
    )

    plan.run_client_with_retry()

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "transport_matters.backend_started"
    assert payload["agent"] == "claude"
    assert payload["runId"] == "run-001"
    assert payload["proxyPort"] == 9900
    assert payload["webPort"] == 9901
    assert payload["baseUrl"] == "http://127.0.0.1:9901"
    route_url = urlparse(payload["routeUrl"])
    assert route_url.scheme == "http"
    assert route_url.netloc == "127.0.0.1:9901"
    assert route_url.path == "/canvas"
    assert parse_qs(route_url.query) == {
        "owner": ["local"],
        "workspace_hash": [payload["workspace"]["hash"]],
        "cli": ["claude"],
        "run_id": ["run-001"],
    }
    assert payload["storageDir"] == str(tmp_path / "storage")
    assert payload["homeDir"] == str(tmp_path / "agent-home")
    assert spawned == [(electron, payload)]


def test_desktop_route_flag_targets_canvas_lab(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def fake_run_client_with_retry(**kwargs: Any) -> None:
        kwargs["on_backend_ready"](
            {
                env_keys.CWD: str(tmp_path),
                env_keys.RUN_ID: "run-002",
            },
            tmp_path / "storage",
            None,
            9900,
            9901,
        )

    plan = prepare_desktop_launch(
        ctx=_DefaultOptionContext(),  # type: ignore[arg-type]
        agent="claude",
        route="canvas-lab",
        base_run_client_with_retry=fake_run_client_with_retry,
        launch_viewer=False,
    )

    plan.run_client_with_retry()

    payload = json.loads(capsys.readouterr().out)
    assert urlparse(payload["routeUrl"]).path == "/canvas-lab"


def test_desktop_print_command_does_not_resolve_electron() -> None:
    def fail_resolve() -> ElectronLaunch:
        raise AssertionError("print-command should not resolve Electron")

    plan = prepare_desktop_launch(
        ctx=_DefaultOptionContext(),  # type: ignore[arg-type]
        agent="claude",
        base_run_client_with_retry=lambda **_kwargs: None,
        launch_viewer=False,
        resolve_electron_launch_func=fail_resolve,
    )

    plan.run_client_with_retry()
