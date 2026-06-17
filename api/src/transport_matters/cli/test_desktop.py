"""Tests for ``transport-matters desktop``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import pytest
import typer
from click.core import ParameterSource
from typer.testing import CliRunner

import transport_matters.cli as cli
from transport_matters import env_keys
from transport_matters.cli import desktop_cmd, main
from transport_matters.cli.desktop_cmd import (
    ElectronLaunch,
    prepare_desktop_launch,
    run_desktop_launch,
    serve_desktop_backend,
)

from ._helpers import _plain

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

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


def test_desktop_accepts_codex_options_as_noops_for_default_claude(tmp_path: Path) -> None:
    codex_bin = tmp_path / "codex"
    codex_bin.write_text("#!/bin/sh\n")

    result = runner.invoke(main, ["desktop", "--print-command", "--codex-bin", str(codex_bin)])

    assert result.exit_code == 0
    assert "_desktop-backend" in result.output


def test_desktop_accepts_claude_options_as_noops_for_codex() -> None:
    result = runner.invoke(
        main,
        ["desktop", "--agent", "codex", "--no-system-prompt", "--print-command"],
    )

    assert result.exit_code == 0
    assert "_desktop-backend" in result.output


def test_desktop_ignores_ambient_cross_agent_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    def fake_run_desktop_launch(**kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(cli, "run_desktop_launch", fake_run_desktop_launch)

    result = runner.invoke(
        main,
        ["desktop", "--agent", "codex", "--print-command"],
        env={env_keys.UPSTREAM_URL: "http://ambient.example"},
    )

    assert result.exit_code == 0
    assert calls == {
        "route": "canvas",
        "work_dir": None,
        "proxy_port": None,
        "web_port": None,
        "storage_dir": None,
        "debug": False,
        "print_command": True,
        "allocate_port_pair_func": cli.allocate_port_pair,
    }


def test_desktop_command_uses_backend_server_path_not_provider_launches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, Any] = {}

    def fail_provider_launch(**_kwargs: Any) -> None:
        raise AssertionError("desktop must not launch a provider command")

    def fake_run_desktop_launch(**kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(cli, "run_start", fail_provider_launch)
    monkeypatch.setattr(cli, "run_codex", fail_provider_launch)
    monkeypatch.setattr(cli, "run_desktop_launch", fake_run_desktop_launch)

    result = runner.invoke(
        main,
        ["desktop", "--agent", "codex", "--work-dir", str(tmp_path), "--", "exec", "hello"],
    )

    assert result.exit_code == 0
    assert calls["work_dir"] == tmp_path
    assert calls["proxy_port"] is None
    assert calls["web_port"] is None
    assert calls["allocate_port_pair_func"] is cli.allocate_port_pair


def test_desktop_command_ignores_passthrough_without_provider_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, Any] = {}

    def fake_run_desktop_launch(**kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(cli, "run_desktop_launch", fake_run_desktop_launch)

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
    assert calls["work_dir"] == tmp_path
    assert "default_client_passthrough" not in calls


def test_desktop_startup_hook_emits_json_and_spawns_electron(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    electron = ElectronLaunch(argv=("/bin/electron", "/app"), cwd=tmp_path)
    spawned: list[tuple[ElectronLaunch, dict[str, Any]]] = []
    served: list[Any] = []

    def fake_serve_backend(plan: Any, on_backend_ready: Any) -> None:
        served.append(plan)
        on_backend_ready()

    run_desktop_launch(
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=tmp_path / "storage",
        resolve_electron_launch_func=lambda: electron,
        spawn_electron_func=lambda launch, event: spawned.append((launch, event)),
        serve_backend_func=fake_serve_backend,
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["type"] == "transport_matters.backend_started"
    assert payload["webPort"] == 9901
    assert payload["baseUrl"] == "http://127.0.0.1:9901"
    route_url = urlparse(payload["routeUrl"])
    assert route_url.scheme == "http"
    assert route_url.netloc == "127.0.0.1:9901"
    assert route_url.path == "/canvas"
    assert parse_qs(route_url.query) == {
        "owner": ["local"],
        "workspace_hash": [payload["workspace"]["hash"]],
    }
    assert "agent" not in payload
    assert "homeDir" not in payload
    assert "proxyPort" not in payload
    assert "runId" not in payload
    assert payload["storageDir"] == str(tmp_path / "storage")
    assert served[0].env[env_keys.CWD] == str(tmp_path)
    assert spawned == [(electron, payload)]


def test_desktop_backend_env_has_no_initial_run_fields(tmp_path: Path) -> None:
    plan = prepare_desktop_launch(
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=tmp_path / "storage",
        launch_viewer=False,
        env={
            env_keys.AGENT_HOME_DIR: "/tmp/agent-home",
            env_keys.CLI: "claude",
            env_keys.DEFAULT_CLIENT_PASSTHROUGH: '["--model","sonnet"]',
            env_keys.RUN_ID: "run-old",
        },
    )

    assert plan.env[env_keys.CWD] == str(tmp_path)
    assert plan.env[env_keys.PROXY_PORT] == "9900"
    assert plan.env[env_keys.WEB_PORT] == "9901"
    assert plan.env[env_keys.STORAGE_DIR] == str(tmp_path / "storage")
    assert env_keys.AGENT_HOME_DIR not in plan.env
    assert env_keys.CLI not in plan.env
    assert env_keys.DEFAULT_CLIENT_PASSTHROUGH not in plan.env
    assert env_keys.RUN_ID not in plan.env


def test_desktop_backend_server_hard_blocks_on_session_store_preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan = prepare_desktop_launch(
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=tmp_path / "storage",
        launch_viewer=False,
    )
    preflight_calls: list[bool] = []

    def fail_preflight() -> None:
        preflight_calls.append(True)
        raise typer.Exit(2)

    def fail_create_app() -> None:
        raise AssertionError("desktop backend must not serve after failed store preflight")

    monkeypatch.setattr(desktop_cmd, "preflight_session_store_or_exit", fail_preflight)
    monkeypatch.setattr("transport_matters.main.create_app", fail_create_app)

    with pytest.raises(typer.Exit) as exc:
        serve_desktop_backend(plan)

    assert exc.value.exit_code == 2
    assert preflight_calls == [True]


def test_desktop_route_flag_targets_canvas_lab(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def fake_serve_backend(_plan: Any, on_backend_ready: Callable[[], None] | None) -> None:
        assert on_backend_ready is not None
        on_backend_ready()

    run_desktop_launch(
        route="canvas-lab",
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=tmp_path / "storage",
        resolve_electron_launch_func=lambda: ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path),
        spawn_electron_func=lambda _launch, _event: None,
        serve_backend_func=fake_serve_backend,
    )

    payload = json.loads(capsys.readouterr().out)
    assert urlparse(payload["routeUrl"]).path == "/canvas-lab"


def test_desktop_print_command_does_not_resolve_electron(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def fail_resolve() -> ElectronLaunch:
        raise AssertionError("print-command should not resolve Electron")

    def fail_serve(_plan: Any, _on_backend_ready: Any) -> None:
        raise AssertionError("print-command should not serve backend")

    run_desktop_launch(
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        print_command=True,
        resolve_electron_launch_func=fail_resolve,
        serve_backend_func=fail_serve,
    )

    assert "_desktop-backend" in capsys.readouterr().out
