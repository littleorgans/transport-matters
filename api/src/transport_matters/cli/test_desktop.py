"""Tests for ``transport-matters desktop``."""

from __future__ import annotations

import json
import os
import re
import subprocess
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlparse

import pytest
import typer
from typer.testing import CliRunner

import transport_matters.cli as cli
from transport_matters import env_keys
from transport_matters.cli import desktop_cmd, main
from transport_matters.cli.desktop_cmd import (
    ElectronLaunch,
    prepare_desktop_launch,
    run_desktop_detached,
    run_desktop_launch,
    serve_desktop_backend,
)
from transport_matters.cli.desktop_runtime import desktop_record_path, read_live_desktop_record
from transport_matters.cli.net import LOOPBACK_HOST

from ._helpers import _plain

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

runner = CliRunner()


def _mark_backend_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        desktop_cmd,
        "wait_for_port_ready",
        lambda *_args, **_kwargs: True,
    )


def test_desktop_help_lists_backend_shell_options() -> None:
    result = runner.invoke(main, ["desktop", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--work-dir" in output
    assert "--channel" in output
    assert "--web-port" in output
    assert "--storage-dir" in output
    assert "--foreground" in output
    assert "Electron canvas" in output
    assert "--agent" not in output
    assert "--agent-home-dir" not in output
    assert "--claude-bin" not in output
    assert "--codex-bin" not in output
    assert "--force-http-fallback" not in output
    assert "--print-command" not in output
    assert "Pass-through" not in output


@pytest.mark.parametrize(
    "args",
    [
        ["--agent", "codex"],
        ["--agent-home-dir", "/tmp/agent-home"],
        ["--debug"],
        ["--print-command"],
        ["--upstream", "http://example.invalid"],
        ["--claude-bin", "/bin/echo"],
        ["--no-claude"],
        ["--no-system-prompt"],
        ["--codex-bin", "/bin/echo"],
        ["--no-codex"],
        ["--force-http-fallback"],
        ["--", "exec", "hello"],
    ],
)
def test_desktop_rejects_provider_flags_and_passthrough(args: list[str]) -> None:
    result = runner.invoke(main, ["desktop", *args])

    assert result.exit_code == 2
    assert "No such option" in result.output or "Got unexpected extra argument" in result.output


def test_desktop_ignores_ambient_cross_agent_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    def fake_run_desktop_detached(**kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(cli, "run_desktop_detached", fake_run_desktop_detached)

    result = runner.invoke(
        main,
        ["desktop"],
        env={env_keys.UPSTREAM_URL: "http://ambient.example"},
    )

    assert result.exit_code == 0
    assert calls == {
        "channel": None,
        "work_dir": None,
        "web_port": None,
        "storage_dir": None,
        "force_restart": False,
    }


def test_desktop_command_uses_backend_server_path_not_provider_launches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, Any] = {}

    def fail_provider_launch(**_kwargs: Any) -> None:
        raise AssertionError("desktop must not launch a provider command")

    def fake_run_desktop_detached(**kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(cli, "run_start", fail_provider_launch)
    monkeypatch.setattr(cli, "run_codex", fail_provider_launch)
    monkeypatch.setattr(cli, "run_desktop_detached", fake_run_desktop_detached)

    result = runner.invoke(
        main,
        ["desktop", "--work-dir", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert calls["channel"] is None
    assert calls["work_dir"] == tmp_path
    assert calls["web_port"] is None


def test_desktop_command_passes_only_backend_launch_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, Any] = {}

    def fake_run_desktop_detached(**kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(cli, "run_desktop_detached", fake_run_desktop_detached)

    result = runner.invoke(
        main,
        [
            "desktop",
            "--channel",
            "preview",
            "--work-dir",
            str(tmp_path),
            "--web-port",
            "9901",
            "--storage-dir",
            str(tmp_path / "storage"),
            "--force-restart",
        ],
    )

    assert result.exit_code == 0
    assert calls["channel"] == "preview"
    assert calls["work_dir"] == tmp_path
    assert calls["web_port"] == 9901
    assert calls["storage_dir"] == tmp_path / "storage"
    assert calls["force_restart"] is True
    assert set(calls) == {
        "channel",
        "work_dir",
        "web_port",
        "storage_dir",
        "force_restart",
    }


def test_desktop_foreground_dispatches_to_blocking_launch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: dict[str, Any] = {}

    def fake_detached(**_kwargs: Any) -> None:
        raise AssertionError("--foreground must not call detached launch")

    def fake_foreground(**kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(cli, "run_desktop_detached", fake_detached)
    monkeypatch.setattr(cli, "run_desktop_launch", fake_foreground)

    result = runner.invoke(main, ["desktop", "--foreground", "--work-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert calls == {
        "channel": None,
        "work_dir": tmp_path,
        "web_port": None,
        "storage_dir": None,
        "force_restart": False,
    }


def test_desktop_unknown_channel_exits_with_list_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    def fake_run_desktop_detached(**kwargs: Any) -> None:
        calls.update(kwargs)

    monkeypatch.setattr(cli, "run_desktop_detached", fake_run_desktop_detached)

    result = runner.invoke(main, ["desktop", "--channel", "ghost"])

    assert result.exit_code == 2
    assert "unknown channel 'ghost'" in result.output
    assert "transport-matters channel list" in result.output
    assert calls == {}


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
            env_keys.HARNESS: "claude",
            env_keys.DEFAULT_CLIENT_PASSTHROUGH: '["--model","sonnet"]',
            env_keys.RUN_ID: "run-old",
        },
    )

    assert plan.env[env_keys.CWD] == str(tmp_path)
    assert plan.env[env_keys.PROXY_PORT] == "9900"
    assert plan.env[env_keys.WEB_PORT] == "9901"
    assert plan.env[env_keys.STORAGE_DIR] == str(tmp_path / "storage")
    assert env_keys.AGENT_HOME_DIR not in plan.env
    assert env_keys.HARNESS not in plan.env
    assert env_keys.DEFAULT_CLIENT_PASSTHROUGH not in plan.env
    assert env_keys.RUN_ID not in plan.env


def test_desktop_backend_env_and_command_carry_channel(tmp_path: Path) -> None:
    plan = prepare_desktop_launch(
        work_dir=tmp_path,
        storage_dir=tmp_path / "storage",
        launch_viewer=False,
        env={env_keys.CHANNEL: "preview"},
        port_in_use_func=lambda _port: False,
    )

    assert plan.env[env_keys.CHANNEL] == "preview"
    assert plan.env[env_keys.PROXY_PORT] == "8797"
    assert plan.env[env_keys.WEB_PORT] == "8798"
    assert plan.command[-2:] == ("--channel", "preview")
    assert "--proxy-port" in plan.command
    assert "8797" in plan.command
    assert "--web-port" in plan.command
    assert "8798" in plan.command


def test_desktop_channel_default_port_in_use_fails_fast(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with pytest.raises(typer.Exit) as exc:
        prepare_desktop_launch(
            work_dir=tmp_path,
            storage_dir=tmp_path / "storage",
            launch_viewer=False,
            env={env_keys.CHANNEL: "preview"},
            port_in_use_func=lambda port: port == 8797,
        )

    assert exc.value.exit_code == 2
    stderr = capsys.readouterr().err
    assert "proxy port 8797 is already in use" in stderr
    assert "pick a different port with --proxy-port" in stderr


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


def test_run_desktop_detached_activates_channel_before_prepare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _mark_backend_ready(monkeypatch)
    calls: list[str] = []
    electron = ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path)

    def fake_activate(channel: str | None) -> SimpleNamespace:
        assert channel == "preview"
        calls.append("activate")
        return SimpleNamespace(id="preview")

    def fake_prepare(**kwargs: Any) -> desktop_cmd.DesktopLaunchPlan:
        calls.append("prepare")
        assert calls == ["activate", "prepare"]
        return desktop_cmd.DesktopLaunchPlan(
            command=("transport-matters", "_desktop-backend"),
            electron_launch=electron,
            env={
                env_keys.CWD: str(tmp_path),
                env_keys.PROXY_PORT: "9900",
                env_keys.STORAGE_DIR: str(tmp_path / "storage"),
                env_keys.WEB_PORT: "9901",
            },
            event={"storageDir": str(tmp_path / "storage")},
            web_port=9901,
        )

    monkeypatch.setattr(desktop_cmd, "activate_channel", fake_activate)
    monkeypatch.setattr(desktop_cmd, "prepare_desktop_launch", fake_prepare)

    run_desktop_detached(
        channel="preview",
        work_dir=tmp_path,
        storage_dir=tmp_path / "storage",
        spawn_electron_func=lambda _launch, _event: calls.append("electron"),
        popen_func=lambda *_args, **_kwargs: SimpleNamespace(pid=4321),
    )

    assert calls == ["activate", "prepare", "electron"]


def test_run_desktop_detached_viewer_env_carries_activated_channel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _mark_backend_ready(monkeypatch)
    monkeypatch.delenv(env_keys.CHANNEL, raising=False)
    assert env_keys.CHANNEL not in os.environ
    electron = ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path)
    viewer_calls: list[dict[str, Any]] = []

    def fake_viewer_popen(args: list[str], **kwargs: Any) -> SimpleNamespace:
        viewer_calls.append({"args": args, **kwargs})
        return SimpleNamespace(pid=6543)

    monkeypatch.setattr(subprocess, "Popen", fake_viewer_popen)

    run_desktop_detached(
        channel="preview",
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=tmp_path / "storage",
        resolve_electron_launch_func=lambda: electron,
        popen_func=lambda *_args, **_kwargs: SimpleNamespace(pid=5432),
    )

    assert len(viewer_calls) == 1
    assert viewer_calls[0]["env"][env_keys.CHANNEL] == "preview"


def test_run_desktop_detached_popen_record_and_viewer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _mark_backend_ready(monkeypatch)
    electron = ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path)
    popen_calls: list[dict[str, Any]] = []
    spawned: list[tuple[ElectronLaunch, dict[str, Any]]] = []

    def fake_popen(args: list[str], **kwargs: Any) -> SimpleNamespace:
        popen_calls.append({"args": args, **kwargs})
        return SimpleNamespace(pid=5432)

    run_desktop_detached(
        channel="preview",
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=tmp_path / "storage",
        resolve_electron_launch_func=lambda: electron,
        spawn_electron_func=lambda launch, event: spawned.append((launch, event)),
        popen_func=fake_popen,
    )

    assert len(popen_calls) == 1
    call = popen_calls[0]
    assert call["args"][:2] == ["transport-matters", "_desktop-backend"]
    assert call["cwd"] == str(tmp_path)
    assert call["env"][env_keys.CHANNEL] == "preview"
    assert call["env"][env_keys.PROXY_PORT] == "9900"
    assert call["stdin"] is subprocess.DEVNULL
    assert call["stderr"] is subprocess.STDOUT
    assert call["close_fds"] is True
    assert call["start_new_session"] is True
    assert call["stdout"].name == str(tmp_path / "storage" / "runtime" / "desktop.log")

    record_file = desktop_record_path(tmp_path / "storage")
    record = read_live_desktop_record(record_file, pid_alive=lambda pid: pid == 5432)
    assert record is not None
    assert record.channel == "preview"
    assert record.proxy_port == 9900
    assert record.web_port == 9901
    assert record.log_path == str(tmp_path / "storage" / "runtime" / "desktop.log")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record.started_at)
    assert len(spawned) == 1
    assert spawned[0][0] == electron
    assert spawned[0][1]["storageDir"] == str(tmp_path / "storage")


def test_run_desktop_detached_waits_for_backend_before_viewer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    electron = ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path)

    def fake_popen(args: list[str], **kwargs: Any) -> SimpleNamespace:
        events.append("popen")
        return SimpleNamespace(pid=5432)

    def fake_wait_for_port_ready(host: str, port: int, *, timeout: float) -> bool:
        events.append("wait")
        assert host == LOOPBACK_HOST
        assert port == 9901
        assert timeout == desktop_cmd._BACKEND_READY_TIMEOUT_S
        return True

    def fake_spawn(_launch: ElectronLaunch, _event: dict[str, Any]) -> None:
        events.append("electron")

    monkeypatch.setattr(desktop_cmd, "wait_for_port_ready", fake_wait_for_port_ready)

    run_desktop_detached(
        channel="preview",
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=tmp_path / "storage",
        resolve_electron_launch_func=lambda: electron,
        spawn_electron_func=fake_spawn,
        popen_func=fake_popen,
    )

    assert events == ["popen", "wait", "electron"]


def test_run_desktop_detached_timeout_does_not_spawn_viewer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spawned: list[ElectronLaunch] = []
    process = SimpleNamespace(pid=5432, poll=lambda: None)
    monkeypatch.setattr(
        desktop_cmd,
        "wait_for_port_ready",
        lambda *_args, **_kwargs: False,
    )

    with pytest.raises(typer.Exit) as exc:
        run_desktop_detached(
            channel="preview",
            work_dir=tmp_path,
            proxy_port=9900,
            web_port=9901,
            storage_dir=tmp_path / "storage",
            resolve_electron_launch_func=lambda: ElectronLaunch(
                argv=("/bin/electron",), cwd=tmp_path
            ),
            spawn_electron_func=lambda launch, _event: spawned.append(launch),
            popen_func=lambda *_args, **_kwargs: process,
        )

    assert exc.value.exit_code == 1
    assert spawned == []
    err = capsys.readouterr().err
    assert "desktop backend did not become ready on http://127.0.0.1:9901" in err
    assert "transport-matters tail preview" in err
    assert str(tmp_path / "storage" / "runtime" / "desktop.log") in err
    record = read_live_desktop_record(
        desktop_record_path(tmp_path / "storage"), pid_alive=lambda pid: pid == 5432
    )
    assert record is not None


def test_run_desktop_detached_timeout_reports_early_backend_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spawned: list[ElectronLaunch] = []
    process = SimpleNamespace(pid=5432, poll=lambda: 42)
    monkeypatch.setattr(
        desktop_cmd,
        "wait_for_port_ready",
        lambda *_args, **_kwargs: False,
    )

    with pytest.raises(typer.Exit) as exc:
        run_desktop_detached(
            channel="preview",
            work_dir=tmp_path,
            proxy_port=9900,
            web_port=9901,
            storage_dir=tmp_path / "storage",
            resolve_electron_launch_func=lambda: ElectronLaunch(
                argv=("/bin/electron",), cwd=tmp_path
            ),
            spawn_electron_func=lambda launch, _event: spawned.append(launch),
            popen_func=lambda *_args, **_kwargs: process,
        )

    assert exc.value.exit_code == 1
    assert spawned == []
    err = capsys.readouterr().err
    assert "desktop backend exited before it became ready" in err
    assert "exit code 42" in err
    assert "transport-matters tail preview" in err


def test_run_desktop_detached_electron_failure_leaves_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _mark_backend_ready(monkeypatch)

    def fail_spawn(_launch: ElectronLaunch, _event: dict[str, Any]) -> None:
        raise desktop_cmd.ElectronResolutionError("viewer failed")

    with pytest.raises(typer.Exit) as exc:
        run_desktop_detached(
            channel="preview",
            work_dir=tmp_path,
            proxy_port=9900,
            web_port=9901,
            storage_dir=tmp_path / "storage",
            resolve_electron_launch_func=lambda: ElectronLaunch(
                argv=("/bin/electron",), cwd=tmp_path
            ),
            spawn_electron_func=fail_spawn,
            popen_func=lambda *_args, **_kwargs: SimpleNamespace(pid=6543),
        )

    assert exc.value.exit_code == 2
    record = read_live_desktop_record(
        desktop_record_path(tmp_path / "storage"), pid_alive=lambda pid: pid == 6543
    )
    assert record is not None
    assert record.pid == 6543
