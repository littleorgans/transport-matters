from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import subprocess
    from pathlib import Path

    import pytest

from transport_matters.shared_proxy import process as process_module
from transport_matters.shared_proxy.process import SupervisorSharedProxyProcess
from transport_matters.supervisor_core import ProcessSupervisor
from transport_matters.supervisor_models import ManagedProcess


class _FakePopen:
    def __init__(self, *, pid: int) -> None:
        self.pid = pid

    def poll(self) -> int | None:
        return None


class _RecordingSupervisor(ProcessSupervisor):
    def __init__(self, *, pid: int, events: list[str] | None = None) -> None:
        super().__init__()
        self.pid = pid
        self.events = events if events is not None else []
        self.argv: list[str] | None = None
        self.env: dict[str, str] | None = None
        self.log_path: Path | None = None

    def spawn(
        self,
        name: str,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        log_path: Path | None = None,
        foreground: bool = False,
        pty: bool = False,
    ) -> ManagedProcess:
        self.events.append("spawn")
        self.argv = argv
        self.env = env
        self.log_path = log_path
        return ManagedProcess(
            name=name,
            popen=cast("subprocess.Popen[bytes]", _FakePopen(pid=self.pid)),
            log_path=log_path,
            process_group=self.pid,
        )


def test_start_writes_pid_file_and_terminate_removes_it(tmp_path: Path) -> None:
    supervisor = _RecordingSupervisor(pid=2222)
    shared_proxy = _make_process(tmp_path, supervisor=supervisor)

    shared_proxy.start()

    record = _read_pid_file(tmp_path)
    assert record == {
        "pid": 2222,
        "control_socket": str(_control_socket(tmp_path)),
        "process_name": process_module.SHARED_PROXY_PROCESS_NAME,
    }

    shared_proxy.terminate()

    assert not _pid_file(tmp_path).exists()


def test_start_reaps_matching_prior_process_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale_pid = 1111
    new_pid = 2222
    events: list[str] = []
    _write_pid_file(tmp_path, pid=stale_pid)
    _stub_liveness(monkeypatch, stale_pid=stale_pid)
    monkeypatch.setattr(
        process_module,
        "_read_process_command",
        lambda pid: _matching_command(tmp_path) if pid == stale_pid else None,
    )

    def fake_terminate(pid: int, *, grace_seconds: float) -> None:
        assert grace_seconds == 2.0
        events.append(f"terminate:{pid}")

    monkeypatch.setattr(process_module, "_terminate_prior_process", fake_terminate)
    supervisor = _RecordingSupervisor(pid=new_pid, events=events)
    shared_proxy = _make_process(tmp_path, supervisor=supervisor)

    shared_proxy.start()

    assert events == [f"terminate:{stale_pid}", "spawn"]
    assert _read_pid_file(tmp_path)["pid"] == new_pid


def test_start_unlinks_dead_pid_file_without_kill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_pid_file(tmp_path, pid=1111)
    monkeypatch.setattr(process_module, "is_pid_alive", lambda pid: False)

    def fail_terminate(pid: int, *, grace_seconds: float) -> None:
        raise AssertionError("dead pid must not be signaled")

    monkeypatch.setattr(process_module, "_terminate_prior_process", fail_terminate)
    supervisor = _RecordingSupervisor(pid=2222)
    shared_proxy = _make_process(tmp_path, supervisor=supervisor)

    shared_proxy.start()

    assert supervisor.events == ["spawn"]
    assert _read_pid_file(tmp_path)["pid"] == 2222


def test_start_refuses_to_kill_non_matching_live_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale_pid = 1111
    _write_pid_file(tmp_path, pid=stale_pid)
    _stub_liveness(monkeypatch, stale_pid=stale_pid)
    monkeypatch.setattr(process_module, "_read_process_command", lambda pid: "/bin/sleep 60")

    def fail_terminate(pid: int, *, grace_seconds: float) -> None:
        raise AssertionError("non matching pid must not be signaled")

    monkeypatch.setattr(process_module, "_terminate_prior_process", fail_terminate)
    supervisor = _RecordingSupervisor(pid=2222)
    shared_proxy = _make_process(tmp_path, supervisor=supervisor)

    shared_proxy.start()

    assert supervisor.events == ["spawn"]
    assert _read_pid_file(tmp_path)["pid"] == 2222


def _make_process(tmp_path: Path, *, supervisor: ProcessSupervisor) -> SupervisorSharedProxyProcess:
    return SupervisorSharedProxyProcess(
        control_socket=_control_socket(tmp_path),
        runtime_dir=tmp_path,
        supervisor=supervisor,
        python_executable="/usr/bin/python3",
        env={},
        accept_probe_timeout_s=0.1,
    )


def _write_pid_file(tmp_path: Path, *, pid: int) -> None:
    _pid_file(tmp_path).write_text(
        json.dumps(
            {
                "pid": pid,
                "control_socket": str(_control_socket(tmp_path)),
                "process_name": process_module.SHARED_PROXY_PROCESS_NAME,
            }
        ),
        encoding="utf-8",
    )


def _read_pid_file(tmp_path: Path) -> dict[str, object]:
    return cast("dict[str, object]", json.loads(_pid_file(tmp_path).read_text()))


def _stub_liveness(monkeypatch: pytest.MonkeyPatch, *, stale_pid: int) -> None:
    monkeypatch.setattr(process_module, "is_pid_alive", lambda pid: pid == stale_pid)


def _matching_command(tmp_path: Path) -> str:
    return (
        "/usr/bin/python3 -m transport_matters.shared_proxy.subprocess "
        f"--control-socket {_control_socket(tmp_path)}"
    )


def _pid_file(tmp_path: Path) -> Path:
    return tmp_path / "shared-proxy.pid"


def _control_socket(tmp_path: Path) -> Path:
    return tmp_path / "shared-proxy.sock"
