from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect, WebSocketState

from transport_matters.api.v1 import captured_terminal
from transport_matters.api.v1.terminal_bridge import spawn_pty_process as _spawn_pty_process
from transport_matters.api.v1.test_terminal import (
    BACKEND_ORIGIN,
    _receive_until_disconnect,
    _wait_until,
    _websocket_headers,
)
from transport_matters.captured_run import (
    CapturedRunDependencies,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
)
from transport_matters.config import get_settings
from transport_matters.main import create_app

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

    from pytest import MonkeyPatch

    from transport_matters.api.v1.terminal_bridge import TerminalPty


CAPTURED_TERMINAL_ROUTE = "/api/captured-runs/claude/terminal"


@dataclass(slots=True)
class FakeLease:
    manifest_path: Path
    sessions: list[TerminalPty]
    closed: bool = False
    lock_released: bool = False
    child_poll_at_close: int | None = None

    def close(self) -> None:
        self.closed = True
        self.lock_released = True
        if self.sessions:
            self.child_poll_at_close = self.sessions[0].process.poll()
        self.manifest_path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class FakeManagedClient:
    name: str
    display_name: str
    argv: list[str]
    env: Mapping[str, str]
    cwd: Path


@dataclass(frozen=True, slots=True)
class FakeManagedSession:
    native_session_id: str
    source_descriptor: str


def test_captured_terminal_rejects_origin_before_spawn(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    prepare_called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal prepare_called
        prepare_called = True
        raise AssertionError("prepare should not run before origin gate")

    monkeypatch.setattr(captured_terminal, "prepare_captured_run", fail_if_called)
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
    assert prepare_called is False


def test_captured_terminal_rejects_non_loopback_host_before_spawn(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    prepare_called = False

    def fail_if_called(*_args: object, **_kwargs: object) -> object:
        nonlocal prepare_called
        prepare_called = True
        raise AssertionError("prepare should not run before host gate")

    monkeypatch.setattr(captured_terminal, "prepare_captured_run", fail_if_called)
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            CAPTURED_TERMINAL_ROUTE,
            headers=_websocket_headers(
                "http://evil.test:8788",
                host="evil.test:8788",
            ),
        ),
    ):
        pass

    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION
    assert prepare_called is False


def test_captured_terminal_sends_ready_before_terminal_bytes(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_prepare(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv("print('TM_CLIENT_BYTES', flush=True)\n"),
    )
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            f"{CAPTURED_TERMINAL_ROUTE}?cwd={quote(str(tmp_path))}",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket,
    ):
        ready = websocket.receive_json()
        output = _receive_until_disconnect(websocket, needle=b"TM_CLIENT_BYTES")
        _receive_until_disconnect(websocket, needle=b"__never__")

    assert ready == {
        "type": "captured-run.ready",
        "runId": "run-test",
        "cwd": str(tmp_path),
        "storageDir": str(tmp_path / "storage"),
        "proxyPort": 9900,
        "webPort": 8788,
        "cli": "claude",
        "nativeSessionId": "native-test",
    }
    assert b"TM_CLIENT_BYTES" in output


def test_captured_terminal_binary_input_reaches_child(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_prepare(
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
        _receive_until_disconnect(websocket, needle=b"__never__")

    assert b"ECHO:ping" in output


def test_captured_terminal_resize_control_applies_winsize(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[int, int]] = []
    from transport_matters.api.v1 import terminal_bridge

    original_set_winsize = terminal_bridge.set_winsize

    def tracking_set_winsize(fd: int, *, cols: int, rows: int) -> None:
        original_set_winsize(fd, cols=cols, rows=rows)
        calls.append((cols, rows))

    monkeypatch.setattr(terminal_bridge, "set_winsize", tracking_set_winsize)
    _install_fake_prepare(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv("import sys\nsys.stdin.buffer.readline()\n"),
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
        websocket.send_text('{"type":"resize","cols":120,"rows":33}')
        _wait_until(lambda: (120, 33) in calls)
        websocket.send_bytes(b"\n")
        _receive_until_disconnect(websocket, needle=b"__never__")

    assert (120, 33) in calls


def test_captured_terminal_ctrl_c_interrupts_foreground_child(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_prepare(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv(
            "import time\n"
            "print('TM_READY', flush=True)\n"
            "try:\n"
            "    time.sleep(30)\n"
            "except KeyboardInterrupt:\n"
            "    print('TM_INTERRUPTED', flush=True)\n"
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
        ready_output = _receive_until_disconnect(websocket, needle=b"TM_READY")
        assert b"TM_READY" in ready_output

        websocket.send_bytes(b"\x03")
        interrupted = _receive_until_disconnect(websocket, needle=b"TM_INTERRUPTED")
        _receive_until_disconnect(websocket, needle=b"__never__")

    assert b"TM_INTERRUPTED" in interrupted


def test_captured_terminal_disconnect_kills_child_then_closes_lease(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    sessions: list[TerminalPty] = []
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}")
    lease = FakeLease(manifest_path=manifest_path, sessions=sessions)

    def tracking_spawn(
        *,
        argv: Sequence[str],
        env: Mapping[str, str],
        cwd: Path,
        cols: int,
        rows: int,
    ) -> TerminalPty:
        session = _spawn_pty_process(argv=argv, env=env, cwd=cwd, cols=cols, rows=rows)
        sessions.append(session)
        return session

    async def disconnect_bridge(*_args: object, **_kwargs: object) -> None:
        raise WebSocketDisconnect(status.WS_1000_NORMAL_CLOSURE)

    monkeypatch.setattr(captured_terminal, "spawn_pty_process", tracking_spawn)
    monkeypatch.setattr(captured_terminal, "_bridge_websocket_to_pty", disconnect_bridge)
    _install_fake_prepare(
        monkeypatch,
        tmp_path,
        argv=_python_client_argv("import time\ntime.sleep(30)\n"),
        lease=lease,
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
        _wait_until(lambda: bool(sessions))

    _wait_until(lambda: sessions[0].process.poll() is not None and lease.closed)

    assert sessions[0].process.poll() is not None
    assert lease.child_poll_at_close is not None
    assert lease.closed is True
    assert lease.lock_released is True
    assert not manifest_path.exists()


def test_captured_terminal_launch_failure_sends_error_and_no_manifest(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    manifest_path = tmp_path / "manifest.json"
    _install_fake_dependencies(monkeypatch, tmp_path)

    def fail_prepare(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("launch exploded")

    monkeypatch.setattr(captured_terminal, "prepare_captured_run", fail_prepare)
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            CAPTURED_TERMINAL_ROUTE,
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket,
    ):
        frame = websocket.receive_json()
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_text()

    assert frame == {
        "type": "captured-run.error",
        "code": "launch_failed",
        "message": "launch exploded",
    }
    assert exc_info.value.code == status.WS_1011_INTERNAL_ERROR
    assert not manifest_path.exists()


async def test_captured_terminal_teardown_offloads_when_signal_handlers_disabled(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[str] = []
    started = asyncio.Event()
    loop = asyncio.get_running_loop()

    def blocking_teardown(*_args: object, **_kwargs: object) -> None:
        calls.append("start")
        loop.call_soon_threadsafe(started.set)
        time.sleep(0.25)
        calls.append("end")

    monkeypatch.setattr(captured_terminal, "_teardown_captured_terminal_run", blocking_teardown)
    task = asyncio.create_task(
        captured_terminal._teardown_captured_terminal_run_async(
            None,
            None,
            install_signal_handlers=False,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        assert calls == ["start"]
        assert not task.done()
        await task
        assert calls == ["start", "end"]
    finally:
        if not task.done():
            task.cancel()


async def test_send_error_and_close_skips_send_when_peer_disconnected() -> None:
    class DisconnectedWebSocket:
        application_state = WebSocketState.CONNECTED
        client_state = WebSocketState.DISCONNECTED

        def __init__(self) -> None:
            self.sent = 0
            self.closed = 0

        async def send_json(self, _payload: object) -> None:
            self.sent += 1

        async def close(self, *, _code: int, _reason: str) -> None:
            self.closed += 1

    websocket = DisconnectedWebSocket()

    await captured_terminal._send_error_and_close(
        cast("Any", websocket),
        code="launch_failed",
        message="launch exploded",
    )

    assert websocket.sent == 0
    assert websocket.closed == 0


def _client(monkeypatch: MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(tmp_path))
    get_settings.cache_clear()
    return TestClient(create_app())


def _install_fake_prepare(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    *,
    argv: list[str],
    lease: FakeLease | None = None,
) -> FakeLease:
    _install_fake_dependencies(monkeypatch, tmp_path)
    fake_lease = lease or FakeLease(manifest_path=tmp_path / "manifest.json", sessions=[])

    def fake_prepare(
        request: CapturedRunRequest,
        **_kwargs: object,
    ) -> tuple[CapturedRunSpawnSpec, object]:
        spawn_spec = CapturedRunSpawnSpec(
            run_id="run-test",
            working_dir=cast("Path", request.directory),
            storage_dir=tmp_path / "storage",
            proxy_port=9900,
            web_port=8788,
            mitmdump_log=tmp_path / "storage" / "mitmdump.log",
            client=cast(
                "Any",
                FakeManagedClient(
                    name="claude",
                    display_name="Claude",
                    argv=argv,
                    env={**os.environ, "PYTHONUNBUFFERED": "1", "TERM": "xterm-256color"},
                    cwd=cast("Path", request.directory),
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
        )
        return spawn_spec, fake_lease

    monkeypatch.setattr(captured_terminal, "prepare_captured_run", fake_prepare)
    return fake_lease


def _install_fake_dependencies(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    dependencies = CapturedRunDependencies(
        require_addon=lambda: cast("Any", tmp_path / "addon.py"),
        resolve_mitmdump=lambda: "/bin/mitmdump",
        which=lambda name: f"/bin/{name}",
        port_in_use=lambda _port: False,
        allocate_port_pair=lambda: (9900, 9901),
        inject_system_prompt=lambda passthrough, **_kwargs: list(passthrough),
        user_supplied_system_prompt=lambda _passthrough: False,
        check_session_store=lambda: None,
    )
    monkeypatch.setattr(captured_terminal, "default_claude_run_dependencies", lambda: dependencies)


def _python_client_argv(script: str) -> list[str]:
    return [sys.executable, "-u", "-c", script]
