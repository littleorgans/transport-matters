"""Process supervision for the shared mitmproxy subprocess."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING, Protocol

from transport_matters.supervisor_core import ProcessSupervisor

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from transport_matters.supervisor_models import ManagedProcess

SHARED_PROXY_PROCESS_NAME = "shared-mitmdump"


class SharedProxyProcess(Protocol):
    """Shape required by SharedProxyManager to supervise the subprocess."""

    @property
    def process_id(self) -> int | None: ...

    def is_running(self) -> bool: ...

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

    def start(self) -> None:
        if self.is_running():
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            self.python_executable,
            "-m",
            "transport_matters.shared_proxy.subprocess",
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

    def terminate(self) -> None:
        self.supervisor.terminate_all(grace_seconds=2.0)
