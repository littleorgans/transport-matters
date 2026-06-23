"""Tests for idempotent ``transport-matters desktop`` launch behavior."""

from __future__ import annotations

import signal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
import typer

from transport_matters.cli import desktop_cmd
from transport_matters.cli.desktop_cmd import ElectronLaunch, run_desktop_detached
from transport_matters.cli.desktop_runtime import (
    desktop_record_path,
    read_live_desktop_record,
)

from ._helpers import _plain, _write_desktop_record

if TYPE_CHECKING:
    from pathlib import Path


def test_run_desktop_detached_live_runtime_attaches_without_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_desktop_record(
        storage,
        pid=7654,
        proxy_port=9900,
        web_port=9901,
        cwd=workspace,
        version="test",
    )
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        "transport_matters.desktop_runtime.wait_for_port_ready",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._read_runtime_meta_channel",
        lambda *_args, **_kwargs: "preview",
    )
    electron = ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path)
    spawned: list[tuple[ElectronLaunch, dict[str, Any]]] = []

    run_desktop_detached(
        channel="preview",
        work_dir=tmp_path,
        storage_dir=storage,
        resolve_electron_launch_func=lambda: electron,
        spawn_electron_func=lambda launch, event: spawned.append((launch, event)),
        popen_func=lambda *_args, **_kwargs: pytest.fail("backend should not start"),
    )

    assert len(spawned) == 1
    assert spawned[0][0] == electron
    event = spawned[0][1]
    assert event["cwd"] == str(workspace)
    assert event["storageDir"] == str(storage)
    assert event["webPort"] == 9901
    assert str(event["routeUrl"]).startswith("http://127.0.0.1:9901/canvas?")


def test_run_desktop_detached_absent_runtime_starts_normally(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(desktop_cmd, "wait_for_port_ready", lambda *_args, **_kwargs: True)
    storage = tmp_path / "storage"
    electron = ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path)
    popen_calls: list[dict[str, Any]] = []
    spawned: list[dict[str, Any]] = []

    def fake_popen(args: list[str], **kwargs: Any) -> SimpleNamespace:
        popen_calls.append({"args": args, **kwargs})
        return SimpleNamespace(pid=8765)

    run_desktop_detached(
        channel="preview",
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=storage,
        resolve_electron_launch_func=lambda: electron,
        spawn_electron_func=lambda _launch, event: spawned.append(event),
        popen_func=fake_popen,
    )

    assert len(popen_calls) == 1
    assert popen_calls[0]["args"][:2] == ["transport-matters", "_desktop-backend"]
    assert popen_calls[0]["stdout"].name == str(storage / "runtime" / "desktop.log")
    assert len(spawned) == 1
    record = read_live_desktop_record(
        desktop_record_path(storage), pid_alive=lambda pid: pid == 8765
    )
    assert record is not None


@pytest.mark.parametrize(
    ("pid_alive", "health_ready", "expected_recovery_signals"),
    [(False, True, ()), (True, False, (signal.SIGTERM,))],
)
def test_run_desktop_detached_recovers_stale_or_unhealthy_runtime_before_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    pid_alive: bool,
    health_ready: bool,
    expected_recovery_signals: tuple[int, ...],
) -> None:
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: pid_alive)
    monkeypatch.setattr(
        "transport_matters.desktop_runtime.wait_for_port_ready",
        lambda *_args, **_kwargs: health_ready,
    )
    kill_calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        raise ProcessLookupError

    monkeypatch.setattr("transport_matters.desktop_runtime.os.kill", fake_kill)
    monkeypatch.setattr(desktop_cmd, "wait_for_port_ready", lambda *_args, **_kwargs: True)
    storage = tmp_path / "storage"
    workspace = tmp_path / "workspace"
    record_path = desktop_record_path(storage)
    _write_desktop_record(
        storage,
        pid=987654321,
        proxy_port=9900,
        web_port=9901,
        cwd=workspace,
        version="test",
    )

    def fake_popen(args: list[str], **kwargs: Any) -> SimpleNamespace:
        assert args[:2] == ["transport-matters", "_desktop-backend"]
        assert not record_path.exists()
        return SimpleNamespace(pid=8765)

    run_desktop_detached(
        channel="preview",
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=storage,
        resolve_electron_launch_func=lambda: ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path),
        spawn_electron_func=lambda _launch, _event: None,
        popen_func=fake_popen,
    )

    record = read_live_desktop_record(record_path, pid_alive=lambda pid: pid == 8765)
    assert record is not None
    assert record.pid == 8765
    assert kill_calls == [(987654321, sig) for sig in expected_recovery_signals]


def test_run_desktop_detached_refuses_non_tm_listener(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    with pytest.raises(typer.Exit) as exc:
        run_desktop_detached(
            channel="preview",
            work_dir=tmp_path,
            proxy_port=9900,
            web_port=9901,
            storage_dir=tmp_path / "storage",
            port_in_use_func=lambda port: port == 9900,
            resolve_electron_launch_func=lambda: pytest.fail("viewer should not resolve"),
            popen_func=lambda *_args, **_kwargs: pytest.fail("backend should not start"),
        )

    assert exc.value.exit_code == 2
    stderr = _plain(capsys.readouterr().err)
    assert "proxy port 9900 is already in use" in stderr
    assert "pick a different port with --proxy-port" in stderr
