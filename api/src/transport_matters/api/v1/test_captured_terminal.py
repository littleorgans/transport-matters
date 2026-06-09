from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect, WebSocketState

from transport_matters import config
from transport_matters.api.v1 import captured_terminal, run_routes
from transport_matters.api.v1.test_terminal import _receive_until_disconnect, _wait_until
from transport_matters.captured_run import (
    CLAUDE_CLIENT_NAME,
    CapturedRunDependencies,
    CapturedRunLease,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
)
from transport_matters.main import create_app
from transport_matters.pty_session import TerminalPty, spawn_pty_process
from transport_matters.run_manager import RunManager, RunState

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

CAPTURED_TERMINAL_ROUTE = "/api/captured-runs/claude/terminal"
BACKEND_ORIGIN = "http://localhost:8788"


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


def test_claude_route_contract_is_unchanged_and_specific_first() -> None:
    routes = [getattr(route, "path", "") for route in captured_terminal.router.routes]
    assert routes[:2] == [
        captured_terminal.CAPTURED_CLAUDE_TERMINAL_ROUTE,
        captured_terminal.CAPTURED_TERMINAL_ROUTE,
    ]


def test_unknown_captured_cli_is_rejected_before_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager, _lease = install_real_pty_manager(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv("print('never')\n"),
    )
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/api/captured-runs/not-a-cli/terminal",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ),
    ):
        pass

    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
    assert manager.list() == []


def test_captured_terminal_rejects_origin_before_spawn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager, _lease = install_real_pty_manager(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv("print('never')\n"),
    )
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            CAPTURED_TERMINAL_ROUTE,
            headers=_websocket_headers("http://evil.test"),
        ),
    ):
        pass

    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
    assert manager.list() == []


def test_captured_terminal_sends_ready_before_terminal_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_real_pty_manager(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv(
            "import sys\nsys.stdout.write('hello-ready\\n')\nsys.stdout.flush()\n"
        ),
    )
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            CAPTURED_TERMINAL_ROUTE,
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket,
    ):
        ready = websocket.receive_json()
        assert ready["type"] == "captured-run.ready"
        output = _receive_until_disconnect(websocket, needle=b"hello-ready")

    assert b"hello-ready" in output


def test_captured_terminal_binary_input_reaches_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_real_pty_manager(
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

    with (
        client,
        client.websocket_connect(
            CAPTURED_TERMINAL_ROUTE,
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket,
    ):
        assert websocket.receive_json()["type"] == "captured-run.ready"
        websocket.send_bytes(b"ping\n")
        output = _receive_until_disconnect(websocket, needle=b"ECHO:ping")

    assert b"ECHO:ping" in output


def test_captured_terminal_resize_control_applies_winsize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_real_pty_manager(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv(
            "import fcntl, struct, sys, termios\n"
            "sys.stdout.write('ready\\n')\nsys.stdout.flush()\n"
            "sys.stdin.readline()\n"
            "rows, cols, _, _ = struct.unpack('HHHH', fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b'\\0'*8))\n"
            "sys.stdout.write(f'{cols}x{rows}\\n')\nsys.stdout.flush()\n"
        ),
    )
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            CAPTURED_TERMINAL_ROUTE,
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket,
    ):
        assert websocket.receive_json()["type"] == "captured-run.ready"
        _receive_until_disconnect(websocket, needle=b"ready")
        websocket.send_json({"type": "resize", "cols": 100, "rows": 40})
        websocket.send_bytes(b"\n")
        output = _receive_until_disconnect(websocket, needle=b"100x40")

    assert b"100x40" in output


def test_captured_terminal_ctrl_c_interrupts_foreground_child(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_real_pty_manager(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv(
            "import sys, time\n"
            "sys.stdout.write('ready\\n')\nsys.stdout.flush()\n"
            "try:\n"
            "    time.sleep(30)\n"
            "except KeyboardInterrupt:\n"
            "    sys.stdout.write('interrupted\\n')\nsys.stdout.flush()\n"
        ),
    )
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            CAPTURED_TERMINAL_ROUTE,
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket,
    ):
        assert websocket.receive_json()["type"] == "captured-run.ready"
        _receive_until_disconnect(websocket, needle=b"ready")
        websocket.send_bytes(b"\x03")
        output = _receive_until_disconnect(websocket, needle=b"interrupted")

    assert b"interrupted" in output


def test_captured_terminal_disconnect_stops_run_and_closes_lease(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager, lease = install_real_pty_manager(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv("import time\ntime.sleep(30)\n"),
    )
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            CAPTURED_TERMINAL_ROUTE,
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket,
    ):
        run_id = websocket.receive_json()["runId"]
        _wait_until(lambda: bool(lease.sessions))

    _wait_until(lambda: manager.get(run_id).state is RunState.EXITED and lease.closed)
    assert lease.sessions[0].process.poll() is not None
    assert lease.child_poll_at_close is not None
    assert lease.lock_released is True
    assert not lease.manifest_path.exists()


def test_captured_terminal_launch_failure_sends_error_and_no_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manager = RunManager(
        dependencies=_fake_dependencies(), prepare_run=cast("Any", _raise_prepare_error)
    )
    monkeypatch.setattr(run_routes, "create_run_manager", lambda: manager)
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            CAPTURED_TERMINAL_ROUTE,
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket,
    ):
        assert websocket.receive_json() == {
            "type": "captured-run.error",
            "code": "launch_failed",
            "message": "prepare failed",
        }

    assert manager.list() == []


async def test_send_error_and_close_skips_send_when_peer_disconnected() -> None:
    class DisconnectedWebSocket:
        application_state = object()
        client_state = object()

        async def send_json(self, _payload: dict[str, object]) -> None:
            raise AssertionError("send_json should not be called")

        async def close(self, *, code: int, reason: str = "") -> None:
            self.closed = (code, reason)

    websocket = cast("Any", DisconnectedWebSocket())
    websocket.application_state = WebSocketState.DISCONNECTED
    websocket.client_state = WebSocketState.DISCONNECTED

    sent = await captured_terminal._send_json_if_connected(websocket, {"type": "x"})
    assert sent is False


def install_real_pty_manager(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    argv: list[str],
    lease: FakeLease | None = None,
) -> tuple[RunManager, FakeLease]:
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
                    name=CLAUDE_CLIENT_NAME,
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
            client_name=request.client_name,
        )
        return spawn_spec, cast("CapturedRunLease", fake_lease)

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
    )
    monkeypatch.setattr(run_routes, "create_run_manager", lambda: manager)
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


def _raise_prepare_error(_request: CapturedRunRequest, **_kwargs: object) -> Any:
    raise RuntimeError("prepare failed")


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(tmp_path))
    config.get_settings.cache_clear()
    return TestClient(create_app())


def _python_client_argv(script: str) -> list[str]:
    return [sys.executable, "-u", "-c", script]


def _websocket_headers(origin: str, *, host: str = "localhost:8788") -> dict[str, str]:
    return {"origin": origin, "host": host}
