from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from transport_matters.api.v1 import run_routes
from transport_matters.api.v1.test_run_routes import (
    BACKEND_ORIGIN,
    _client,
    _http_headers,
    _websocket_headers,
)
from transport_matters.api.v1.test_terminal import _receive_until_disconnect, _wait_until
from transport_matters.captured_run import (
    CLAUDE_HARNESS_NAME,
    CapturedRunBindConflict,
    CapturedRunDependencies,
    CapturedRunLease,
    CapturedRunProxyStartTimeout,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
)
from transport_matters.pty_session import TerminalPty, spawn_pty_process
from transport_matters.run_manager import RunManager, RunState

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def test_websocket_binary_input_reaches_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager, _lease = install_real_pty_manager(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv(
            "import sys\n"
            "data = sys.stdin.buffer.readline()\n"
            "sys.stdout.buffer.write(b'ECHO:' + data)\n"
            "sys.stdout.flush()\n"
        ),
    )
    client = _client(monkeypatch, tmp_path)

    with client:
        run_id = client.post(
            "/v1/runs",
            json={"harness": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()["run"]["runId"]
        with client.websocket_connect(
            f"/v1/runs/{run_id}/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket:
            assert websocket.receive_json()["type"] == "run.terminal.ready"
            assert websocket.receive_json() == {"type": "run.terminal.scrollback-end"}
            websocket.send_bytes(b"ping\n")
            output = _receive_until_disconnect(websocket, needle=b"ECHO:ping")
            assert b"ECHO:ping" in output
        _wait_until(lambda: manager.get(run_id).state is RunState.EXITED)


def test_post_launch_failure_returns_machine_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def raise_shared_prepare_error(
        request: CapturedRunRequest,
        *,
        shared_proxy: object,
        dependencies: CapturedRunDependencies,
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
        return _raise_prepare_error(request)

    manager = RunManager(
        dependencies=_fake_dependencies(),
        prepare_run=cast("Any", _raise_prepare_error),
        shared_proxy_manager=cast("Any", object()),
    )
    monkeypatch.setattr(
        "transport_matters.run_manager.prepare_shared_captured_run",
        raise_shared_prepare_error,
    )
    monkeypatch.setattr(run_routes, "create_run_manager", lambda **_: manager)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs",
            json={"harness": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "launch_failed"
    assert manager.list() == []


@pytest.mark.parametrize(
    ("prepare_error", "status_code", "code"),
    [
        (CapturedRunBindConflict("proxy busy"), 409, "bind_conflict"),
        (
            CapturedRunProxyStartTimeout("mitmdump did not come up within 5s."),
            503,
            "proxy_start_timeout",
        ),
    ],
)
def test_post_launch_typed_prepare_errors_return_machine_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    prepare_error: Exception,
    status_code: int,
    code: str,
) -> None:
    async def raise_prepare_error(
        _request: CapturedRunRequest,
        *,
        shared_proxy: object,
        dependencies: CapturedRunDependencies,
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
        raise prepare_error

    manager = RunManager(
        dependencies=_fake_dependencies(),
        prepare_run=cast("Any", raise_prepare_error),
        shared_proxy_manager=cast("Any", object()),
    )
    monkeypatch.setattr(
        "transport_matters.run_manager.prepare_shared_captured_run",
        raise_prepare_error,
    )
    monkeypatch.setattr(run_routes, "create_run_manager", lambda **_: manager)
    client = _client(monkeypatch, tmp_path)

    with client:
        response = client.post(
            "/v1/runs",
            json={"harness": "claude", "cwd": str(tmp_path)},
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code
    assert manager.list() == []


@dataclass
class FakeLease:
    manifest_path: Path
    sessions: list[TerminalPty]
    closed: bool = False
    lock_released: bool = False
    child_poll_at_close: int | None = None

    def close(self) -> None:
        self.child_poll_at_close = self.sessions[0].process.poll() if self.sessions else None
        self.closed = True
        self.lock_released = True
        self.manifest_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class FakeManagedClient:
    name: str
    display_name: str
    argv: list[str]
    env: Mapping[str, str]
    cwd: Path


@dataclass(frozen=True)
class FakeManagedSession:
    native_session_id: str
    source_descriptor: str


def install_real_pty_manager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    argv: list[str],
    lease: FakeLease | None = None,
) -> tuple[RunManager, FakeLease]:
    """Install a RunManager that spawns a real PTY child, with prepare/lease faked."""
    sessions: list[TerminalPty] = []
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}")
    fake_lease = lease or FakeLease(manifest_path=manifest_path, sessions=sessions)

    def fake_prepare(
        request: CapturedRunRequest,
        **_kwargs: object,
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
        working_dir = cast("Path", request.directory)
        spawn_spec = CapturedRunSpawnSpec(
            run_id="run-test",
            working_dir=working_dir,
            storage_dir=tmp_path / "storage",
            proxy_port=9900,
            web_port=None,
            mitmdump_log=tmp_path / "storage" / "mitmdump.log",
            client=cast(
                "Any",
                FakeManagedClient(
                    name=CLAUDE_HARNESS_NAME,
                    display_name="Claude",
                    argv=argv,
                    env={**os.environ, "PYTHONUNBUFFERED": "1", "TERM": "xterm-256color"},
                    cwd=working_dir,
                ),
            ),
            launch_env={},
            managed_session=cast(
                "Any",
                FakeManagedSession(
                    native_session_id="native-test",
                    source_descriptor='{"kind":"claude"}',
                ),
            ),
            harness=request.harness,
        )
        return spawn_spec, cast("CapturedRunLease", fake_lease)

    async def fake_prepare_shared(
        request: CapturedRunRequest,
        *,
        shared_proxy: object,
        dependencies: CapturedRunDependencies,
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
        return fake_prepare(request)

    def tracking_spawn(
        *,
        argv: Sequence[str],
        env: Mapping[str, str],
        cwd: Path,
        cols: int,
        rows: int,
    ) -> TerminalPty:
        session = spawn_pty_process(argv=argv, env=env, cwd=cwd, cols=cols, rows=rows)
        sessions.append(session)
        return session

    manager = RunManager(
        dependencies=_fake_dependencies(),
        prepare_run=fake_prepare,
        spawn_pty=tracking_spawn,
        shared_proxy_manager=cast("Any", object()),
    )
    monkeypatch.setattr(
        "transport_matters.run_manager.prepare_shared_captured_run",
        fake_prepare_shared,
    )
    monkeypatch.setattr(run_routes, "create_run_manager", lambda **_: manager)
    return manager, fake_lease


def _fake_dependencies() -> CapturedRunDependencies:
    return CapturedRunDependencies(
        require_addon=lambda: Path("addon.py"),
        resolve_mitmdump=lambda: "mitmdump",
        which=lambda *_args, **_kwargs: "fake",
        port_in_use=lambda _port: False,
        allocate_port_pair=lambda: (8787, 8788),
        inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
        user_supplied_system_prompt=lambda _args: False,
        check_session_store=lambda: None,
    )


def _raise_prepare_error(
    _request: CapturedRunRequest,
) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
    raise RuntimeError("prepare failed")


def _python_client_argv(script: str) -> list[str]:
    return [sys.executable, "-c", script]
