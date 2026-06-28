"""Tests for idempotent ``transport-matters desktop`` launch behavior."""

from __future__ import annotations

import signal
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
import typer

from transport_matters.cli import desktop_cmd
from transport_matters.cli.desktop_cmd import (
    ElectronLaunch,
    run_desktop_detached,
    run_desktop_launch,
)
from transport_matters.cli.desktop_runtime import (
    DesktopHealthProbeResult,
    DesktopLivenessPolicy,
    desktop_record_path,
    read_live_desktop_record,
)

from ._helpers import _plain, _write_desktop_record

if TYPE_CHECKING:
    from pathlib import Path


def _patch_live_desktop_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    channel: str = "preview",
    cwd: Path | None = None,
) -> None:
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._probe_desktop_health",
        lambda *_args, **_kwargs: DesktopHealthProbeResult(status="live"),
    )
    meta = SimpleNamespace(channel=channel, cwd=str(cwd) if cwd is not None else None)
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._read_runtime_meta",
        lambda *_args, **_kwargs: meta,
    )


def _patch_record_stop(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    kill_calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        raise ProcessLookupError

    monkeypatch.setattr("transport_matters.desktop_runtime.os.kill", fake_kill)
    return kill_calls


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
    _patch_live_desktop_runtime(monkeypatch, cwd=workspace)
    electron = ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path)
    spawned: list[tuple[ElectronLaunch, dict[str, Any]]] = []

    run_desktop_detached(
        channel="preview",
        work_dir=workspace,
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


def test_run_desktop_detached_reclaims_live_different_workdir_before_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(desktop_cmd, "wait_for_port_ready", lambda *_args, **_kwargs: True)
    storage = tmp_path / "storage"
    old_workspace = tmp_path / "old-workspace"
    new_workspace = tmp_path / "new-workspace"
    old_workspace.mkdir()
    new_workspace.mkdir()
    _write_desktop_record(
        storage,
        pid=7654,
        proxy_port=9900,
        web_port=9901,
        cwd=new_workspace,
        version="test",
    )
    _patch_live_desktop_runtime(monkeypatch, cwd=old_workspace)
    kill_calls = _patch_record_stop(monkeypatch)
    electron = ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path)
    popen_calls: list[dict[str, Any]] = []
    spawned: list[dict[str, Any]] = []

    def fake_popen(args: list[str], **kwargs: Any) -> SimpleNamespace:
        popen_calls.append({"args": args, **kwargs})
        return SimpleNamespace(pid=8765)

    run_desktop_detached(
        channel="preview",
        work_dir=new_workspace,
        proxy_port=9900,
        web_port=9901,
        storage_dir=storage,
        resolve_electron_launch_func=lambda: electron,
        spawn_electron_func=lambda _launch, event: spawned.append(event),
        popen_func=fake_popen,
    )

    assert kill_calls == [(7654, signal.SIGTERM)]
    assert len(popen_calls) == 1
    assert popen_calls[0]["cwd"] == str(new_workspace.resolve())
    assert popen_calls[0]["env"]["TRANSPORT_MATTERS_CWD"] == str(new_workspace.resolve())
    assert len(spawned) == 1
    assert spawned[0]["cwd"] == str(new_workspace.resolve())
    record = read_live_desktop_record(
        desktop_record_path(storage), pid_alive=lambda pid: pid == 8765
    )
    assert record is not None
    assert record.cwd == str(new_workspace.resolve())


def test_run_desktop_launch_live_runtime_attaches_without_serving(
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
    _patch_live_desktop_runtime(monkeypatch, cwd=workspace)
    electron = ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path)
    spawned: list[tuple[ElectronLaunch, dict[str, Any]]] = []

    run_desktop_launch(
        channel="preview",
        work_dir=workspace,
        storage_dir=storage,
        resolve_electron_launch_func=lambda: electron,
        spawn_electron_func=lambda launch, event: spawned.append((launch, event)),
        serve_backend_func=lambda *_args, **_kwargs: pytest.fail("backend should not serve"),
    )

    assert len(spawned) == 1
    event = spawned[0][1]
    assert event["cwd"] == str(workspace)
    assert event["storageDir"] == str(storage)
    assert event["webPort"] == 9901


def test_run_desktop_launch_reclaims_live_different_workdir_before_serving(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    storage = tmp_path / "storage"
    old_workspace = tmp_path / "old-workspace"
    new_workspace = tmp_path / "new-workspace"
    old_workspace.mkdir()
    new_workspace.mkdir()
    _write_desktop_record(
        storage,
        pid=7654,
        proxy_port=9900,
        web_port=9901,
        cwd=new_workspace,
        version="test",
    )
    _patch_live_desktop_runtime(monkeypatch, cwd=old_workspace)
    kill_calls = _patch_record_stop(monkeypatch)
    attached: list[tuple[ElectronLaunch, dict[str, Any]]] = []
    served: list[Any] = []

    run_desktop_launch(
        channel="preview",
        work_dir=new_workspace,
        proxy_port=9900,
        web_port=9901,
        storage_dir=storage,
        resolve_electron_launch_func=lambda: ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path),
        spawn_electron_func=lambda launch, event: attached.append((launch, event)),
        serve_backend_func=lambda plan, _on_ready: served.append(plan),
    )

    assert kill_calls == [(7654, signal.SIGTERM)]
    assert attached == []
    assert len(served) == 1
    assert served[0].event["cwd"] == str(new_workspace.resolve())
    assert served[0].env["TRANSPORT_MATTERS_CWD"] == str(new_workspace.resolve())


def test_run_desktop_launch_recovers_dead_pid_before_serving(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: False)
    storage = tmp_path / "storage"
    record_path = desktop_record_path(storage)
    _write_desktop_record(
        storage,
        pid=987654321,
        proxy_port=9900,
        web_port=9901,
        cwd=tmp_path / "workspace",
        version="test",
    )
    served: list[Any] = []

    def fake_serve(plan: Any, _on_ready: Any) -> None:
        assert not record_path.exists()
        served.append(plan)

    run_desktop_launch(
        channel="preview",
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=storage,
        resolve_electron_launch_func=lambda: ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path),
        serve_backend_func=fake_serve,
    )

    assert len(served) == 1


def test_run_desktop_launch_recovers_wedged_runtime_after_debounce(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr("transport_matters.desktop_runtime.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._probe_desktop_health",
        lambda *_args, **_kwargs: DesktopHealthProbeResult(status="timeout"),
    )
    kill_calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        raise ProcessLookupError

    monkeypatch.setattr("transport_matters.desktop_runtime.os.kill", fake_kill)
    storage = tmp_path / "storage"
    _write_desktop_record(
        storage,
        pid=987654321,
        proxy_port=9900,
        web_port=9901,
        cwd=tmp_path / "workspace",
        version="test",
    )
    served: list[Any] = []

    run_desktop_launch(
        channel="preview",
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=storage,
        resolve_electron_launch_func=lambda: ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path),
        serve_backend_func=lambda plan, _on_ready: served.append(plan),
    )

    assert len(served) == 1
    assert kill_calls == [(987654321, signal.SIGTERM)]


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


def test_run_desktop_detached_recovers_dead_pid_before_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: False)
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._probe_desktop_health",
        lambda *_args, **_kwargs: DesktopHealthProbeResult(status="live"),
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
    assert kill_calls == []


def test_run_desktop_detached_recovers_refused_runtime_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr("transport_matters.desktop_runtime.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._probe_desktop_health",
        lambda *_args, **_kwargs: DesktopHealthProbeResult(status="refused"),
    )
    monkeypatch.setattr(desktop_cmd, "wait_for_port_ready", lambda *_args, **_kwargs: True)
    kill_calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        raise ProcessLookupError

    monkeypatch.setattr("transport_matters.desktop_runtime.os.kill", fake_kill)
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

    run_desktop_detached(
        channel="preview",
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=storage,
        resolve_electron_launch_func=lambda: ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path),
        spawn_electron_func=lambda _launch, _event: None,
        popen_func=lambda _args, **_kwargs: SimpleNamespace(pid=8765),
    )

    stderr = _plain(capsys.readouterr().err)
    assert "channel preview" in stderr
    assert "pid 987654321" in stderr
    assert "refused connections" in stderr
    record = read_live_desktop_record(record_path, pid_alive=lambda pid: pid == 8765)
    assert record is not None
    assert record.pid == 8765
    assert kill_calls == [(987654321, signal.SIGTERM)]


def test_run_desktop_detached_transient_timeout_retries_then_attaches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr("transport_matters.desktop_runtime.time.sleep", lambda _seconds: None)
    probe_results = [
        DesktopHealthProbeResult(status="timeout"),
        DesktopHealthProbeResult(status="live"),
    ]
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._probe_desktop_health",
        lambda *_args, **_kwargs: probe_results.pop(0),
    )
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._read_runtime_meta",
        lambda *_args, **_kwargs: SimpleNamespace(channel="preview", cwd=None),
    )
    kill_calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        "transport_matters.desktop_runtime.os.kill",
        lambda pid, sig: kill_calls.append((pid, sig)),
    )
    storage = tmp_path / "storage"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _write_desktop_record(
        storage,
        pid=987654321,
        proxy_port=9900,
        web_port=9901,
        cwd=workspace,
        version="test",
    )
    spawned: list[dict[str, Any]] = []

    run_desktop_detached(
        channel="preview",
        work_dir=workspace,
        storage_dir=storage,
        liveness_policy=DesktopLivenessPolicy(attempts=2, backoff_s=0.01),
        resolve_electron_launch_func=lambda: ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path),
        spawn_electron_func=lambda _launch, event: spawned.append(event),
        popen_func=lambda *_args, **_kwargs: pytest.fail("backend should not start"),
    )

    assert len(spawned) == 1
    assert kill_calls == []


def test_run_desktop_detached_recovers_wedged_runtime_after_debounce(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr("transport_matters.desktop_runtime.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._probe_desktop_health",
        lambda *_args, **_kwargs: DesktopHealthProbeResult(status="timeout"),
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

    run_desktop_detached(
        channel="preview",
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=storage,
        resolve_electron_launch_func=lambda: ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path),
        spawn_electron_func=lambda _launch, _event: None,
        popen_func=lambda _args, **_kwargs: SimpleNamespace(pid=8765),
    )

    stderr = _plain(capsys.readouterr().err)
    assert "channel preview" in stderr
    assert "pid 987654321" in stderr
    assert "http://127.0.0.1:9901/health" in stderr
    assert "did not answer after liveness retries" in stderr
    record = read_live_desktop_record(record_path, pid_alive=lambda pid: pid == 8765)
    assert record is not None
    assert record.pid == 8765
    assert kill_calls == [(987654321, signal.SIGTERM)]


@pytest.mark.parametrize(
    "probe_results",
    [
        [DesktopHealthProbeResult(status="failed"), DesktopHealthProbeResult(status="refused")],
        [DesktopHealthProbeResult(status="refused"), DesktopHealthProbeResult(status="failed")],
    ],
)
def test_run_desktop_detached_refuses_mixed_probe_results_without_kill(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe_results: list[DesktopHealthProbeResult],
) -> None:
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr("transport_matters.desktop_runtime.time.sleep", lambda _seconds: None)
    results = probe_results.copy()
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._probe_desktop_health",
        lambda *_args, **_kwargs: results.pop(0),
    )
    monkeypatch.setattr(desktop_cmd, "wait_for_port_ready", lambda *_args, **_kwargs: True)
    kill_calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        raise ProcessLookupError

    monkeypatch.setattr("transport_matters.desktop_runtime.os.kill", fake_kill)
    storage = tmp_path / "storage"
    _write_desktop_record(
        storage,
        pid=987654321,
        proxy_port=9900,
        web_port=9901,
        cwd=tmp_path / "workspace",
        version="test",
    )

    with pytest.raises(typer.Exit) as exc:
        run_desktop_detached(
            channel="preview",
            work_dir=tmp_path,
            storage_dir=storage,
            liveness_policy=DesktopLivenessPolicy(attempts=len(probe_results), backoff_s=0.01),
            resolve_electron_launch_func=lambda: pytest.fail("viewer should not resolve"),
            popen_func=lambda *_args, **_kwargs: pytest.fail("backend should not start"),
        )

    assert exc.value.exit_code == 1
    assert kill_calls == []


def test_run_desktop_detached_force_restart_kills_live_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("transport_matters.desktop_runtime.is_pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        "transport_matters.desktop_runtime._probe_desktop_health",
        lambda *_args, **_kwargs: DesktopHealthProbeResult(status="timeout"),
    )
    monkeypatch.setattr(desktop_cmd, "wait_for_port_ready", lambda *_args, **_kwargs: True)
    kill_calls: list[tuple[int, int]] = []

    def fake_kill(pid: int, sig: int) -> None:
        kill_calls.append((pid, sig))
        raise ProcessLookupError

    monkeypatch.setattr("transport_matters.desktop_runtime.os.kill", fake_kill)
    storage = tmp_path / "storage"
    _write_desktop_record(
        storage,
        pid=987654321,
        proxy_port=9900,
        web_port=9901,
        cwd=tmp_path / "workspace",
        version="test",
    )

    run_desktop_detached(
        channel="preview",
        work_dir=tmp_path,
        proxy_port=9900,
        web_port=9901,
        storage_dir=storage,
        force_restart=True,
        resolve_electron_launch_func=lambda: ElectronLaunch(argv=("/bin/electron",), cwd=tmp_path),
        spawn_electron_func=lambda _launch, _event: None,
        popen_func=lambda _args, **_kwargs: SimpleNamespace(pid=8765),
    )

    assert kill_calls == [(987654321, signal.SIGTERM)]


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
