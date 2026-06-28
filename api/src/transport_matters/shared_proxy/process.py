"""Process supervision for the shared mitmproxy subprocess."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from transport_matters.atomic_io import write_atomic_json
from transport_matters.desktop_runtime import is_pid_alive
from transport_matters.supervisor_core import ProcessSupervisor

if TYPE_CHECKING:
    from collections.abc import Mapping

    from transport_matters.supervisor_models import ManagedProcess

SHARED_PROXY_PROCESS_NAME = "shared-mitmdump"
_SHARED_PROXY_PID_FILENAME = "shared-proxy.pid"
_SHARED_PROXY_SUBPROCESS_MODULE = "transport_matters.shared_proxy.subprocess"


@dataclass(frozen=True, slots=True)
class SharedProxyProcessExit:
    """Observed subprocess exit details for startup diagnostics."""

    return_code: int | None
    log_tail: str | None = None

    def message(self) -> str:
        suffix = f"; stderr/log tail: {self.log_tail}" if self.log_tail else ""
        return f"shared proxy subprocess exited early with returncode={self.return_code}{suffix}"


@dataclass(frozen=True, slots=True)
class _SharedProxyPidRecord:
    pid: int
    control_socket: str
    process_name: str


class SharedProxyProcess(Protocol):
    """Shape required by SharedProxyManager to supervise the subprocess."""

    @property
    def process_id(self) -> int | None: ...

    def is_running(self) -> bool: ...

    def exit_status(self) -> SharedProxyProcessExit | None: ...

    def start(self) -> None: ...

    def terminate(self) -> None: ...


class SupervisorSharedProxyProcess:
    """ProcessSupervisor-backed shared mitmproxy subprocess."""

    def __init__(
        self,
        *,
        control_socket: Path,
        runtime_dir: Path,
        supervisor: ProcessSupervisor | None = None,
        python_executable: str | None = None,
        env: Mapping[str, str] | None = None,
        log_path: Path | None = None,
        accept_probe_timeout_s: float = 5.0,
    ) -> None:
        self.control_socket = control_socket
        self.runtime_dir = runtime_dir
        self.supervisor = supervisor or ProcessSupervisor()
        self.python_executable = python_executable or sys.executable
        self.env = dict(env) if env is not None else dict(os.environ)
        self.log_path = log_path or runtime_dir / "logs" / "shared-mitmdump.log"
        self.accept_probe_timeout_s = accept_probe_timeout_s
        self._managed: ManagedProcess | None = None

    @property
    def process_id(self) -> int | None:
        if self._managed is None:
            return None
        return self._managed.popen.pid

    def is_running(self) -> bool:
        return self._managed is not None and self._managed.popen.poll() is None

    def exit_status(self) -> SharedProxyProcessExit | None:
        if self._managed is None:
            return None
        return_code = self._managed.popen.poll()
        if return_code is None:
            return None
        return SharedProxyProcessExit(
            return_code=return_code,
            log_tail=_read_log_tail(self.log_path),
        )

    def start(self) -> None:
        if self.is_running():
            return
        self._reap_prior_instance()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            self.python_executable,
            "-m",
            _SHARED_PROXY_SUBPROCESS_MODULE,
            "--control-socket",
            str(self.control_socket),
            "--accept-probe-timeout-s",
            str(self.accept_probe_timeout_s),
        ]
        env = {**self.env, "PYTHONUNBUFFERED": "1"}
        self._managed = self.supervisor.spawn(
            SHARED_PROXY_PROCESS_NAME,
            argv,
            env=env,
            log_path=self.log_path,
        )
        try:
            _write_pid_record(self._pid_file, self._managed.popen.pid, self.control_socket)
        except OSError:
            self.supervisor.terminate_all(grace_seconds=2.0)
            self._managed = None
            raise

    def terminate(self) -> None:
        self.supervisor.terminate_all(grace_seconds=2.0)
        _unlink_path(self._pid_file)

    @property
    def _pid_file(self) -> Path:
        return self.runtime_dir / _SHARED_PROXY_PID_FILENAME

    def _reap_prior_instance(self) -> None:
        record = _read_pid_record(self._pid_file)
        if record is None:
            _unlink_path(self._pid_file)
            return
        if not _record_matches_current_socket(record, self.control_socket):
            _unlink_path(self._pid_file)
            return
        if not is_pid_alive(record.pid):
            _unlink_path(self._pid_file)
            return
        if not _process_matches_record(record):
            _unlink_path(self._pid_file)
            return
        _terminate_prior_process(record.pid, grace_seconds=2.0)
        _unlink_path(self._pid_file)


def _write_pid_record(path: Path, pid: int, control_socket: Path) -> None:
    write_atomic_json(
        path,
        {
            "pid": pid,
            "control_socket": str(control_socket),
            "process_name": SHARED_PROXY_PROCESS_NAME,
        },
    )


def _read_pid_record(path: Path) -> _SharedProxyPidRecord | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    pid = payload.get("pid")
    control_socket = payload.get("control_socket")
    process_name = payload.get("process_name")
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    if not isinstance(control_socket, str) or not control_socket:
        return None
    if not isinstance(process_name, str) or not process_name:
        return None
    return _SharedProxyPidRecord(
        pid=pid,
        control_socket=control_socket,
        process_name=process_name,
    )


def _record_matches_current_socket(record: _SharedProxyPidRecord, control_socket: Path) -> bool:
    return record.process_name == SHARED_PROXY_PROCESS_NAME and record.control_socket == str(
        control_socket
    )


def _process_matches_record(record: _SharedProxyPidRecord) -> bool:
    command = _read_process_command(record.pid)
    if command is None:
        return False
    return (
        _SHARED_PROXY_SUBPROCESS_MODULE in command
        and "--control-socket" in command
        and record.control_socket in command
    )


def _read_process_command(pid: int) -> str | None:
    proc_cmdline = Path("/proc") / str(pid) / "cmdline"
    try:
        raw_cmdline = proc_cmdline.read_bytes()
    except OSError:
        raw_cmdline = b""
    if raw_cmdline:
        parts = [
            part.decode("utf-8", errors="replace") for part in raw_cmdline.split(b"\0") if part
        ]
        if parts:
            return " ".join(parts)

    try:
        result = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    command = result.stdout.strip()
    return command or None


def _terminate_prior_process(pid: int, *, grace_seconds: float) -> None:
    _signal_process_group_or_pid(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if not is_pid_alive(pid):
            return
        time.sleep(0.05)
    if is_pid_alive(pid):
        _signal_process_group_or_pid(pid, signal.SIGKILL)


def _signal_process_group_or_pid(pid: int, signum: signal.Signals) -> None:
    if _process_group_for_pid(pid) != pid:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signum)
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(pid, signum)


def _process_group_for_pid(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except ProcessLookupError:
        return None


def _unlink_path(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def _read_log_tail(log_path: Path, *, max_bytes: int = 4096) -> str | None:
    try:
        with log_path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read(max_bytes)
    except OSError:
        return None
    tail = data.decode(errors="replace").strip()
    return tail or None
