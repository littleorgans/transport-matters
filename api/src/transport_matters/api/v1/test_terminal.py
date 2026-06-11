from __future__ import annotations

import errno
import os
import select
import signal
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from transport_matters.api.v1 import terminal
from transport_matters.main import create_app

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.testclient import WebSocketTestSession


BACKEND_ORIGIN = "http://localhost:8788"
TERMINAL_ROUTE = "/api/terminal"


def test_terminal_runs_shell_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            f"{TERMINAL_ROUTE}?cols=80&rows=24",
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket,
    ):
        websocket.send_bytes(b"printf hi\nexit\n")
        output = _receive_until_disconnect(websocket, needle=b"hi")

    assert b"hi" in output


def test_terminal_resize_control_applies_winsize(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[int, int]] = []
    original_set_winsize = terminal._set_winsize

    def tracking_set_winsize(fd: int, *, cols: int, rows: int) -> None:
        original_set_winsize(fd, cols=cols, rows=rows)
        calls.append((cols, rows))

    monkeypatch.setattr(terminal, "_set_winsize", tracking_set_winsize)
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            TERMINAL_ROUTE,
            headers=_websocket_headers(BACKEND_ORIGIN),
        ) as websocket,
    ):
        websocket.send_text('{"type":"resize","cols":120,"rows":33}')
        websocket.send_bytes(b"exit\n")
        _receive_until_disconnect(websocket, needle=b"exit")

    assert (120, 33) in calls


def test_terminal_disconnect_kills_child_and_closes_master_fd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sessions: list[terminal.TerminalPty] = []
    original_spawn = terminal._spawn_terminal_pty

    def tracking_spawn(*, cols: int, rows: int, cwd: Path) -> terminal.TerminalPty:
        session = original_spawn(cols=cols, rows=rows, cwd=cwd)
        sessions.append(session)
        return session

    monkeypatch.setattr(terminal, "_spawn_terminal_pty", tracking_spawn)
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            TERMINAL_ROUTE,
            headers=_websocket_headers(BACKEND_ORIGIN),
        ),
    ):
        assert sessions

    session = sessions[0]
    _wait_until(lambda: session.process.poll() is not None and session.closed)

    assert session.process.poll() is not None
    with pytest.raises(OSError):
        os.fstat(session.master_fd)


def test_terminal_ctrl_c_interrupts_foreground_child_when_parent_ignores_sigint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SHELL", _shell_for_tests())
    original_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        session = terminal._spawn_terminal_pty(cols=80, rows=24, cwd=tmp_path)
    finally:
        signal.signal(signal.SIGINT, original_sigint)

    try:
        terminal._write_all(session.master_fd, _python_interrupt_probe_command())
        output = _read_pty_until(
            session.master_fd,
            needle=b"TM_READY",
        )
        assert b"TM_READY" in output

        terminal._write_all(session.master_fd, b"\x03")
        output = _read_pty_until(
            session.master_fd,
            needle=b"TM_INTERRUPTED",
        )

        assert b"TM_INTERRUPTED" in output
    finally:
        terminal._terminate_terminal_pty(session)


def test_terminal_rejects_origin_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            TERMINAL_ROUTE,
            headers=_websocket_headers("http://evil.test"),
        ),
    ):
        pass

    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION


def test_terminal_rejects_non_loopback_host_with_matching_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        # TrustedHostMiddleware (main.py) now denies the untrusted Host before
        # the handshake is even accepted, an earlier rejection than the old
        # accept-then-close-1008 inside the terminal route.
        pytest.raises(WebSocketDenialResponse) as exc_info,
        client.websocket_connect(
            TERMINAL_ROUTE,
            headers=_websocket_headers(
                "http://evil.test:8788",
                host="evil.test:8788",
            ),
        ),
    ):
        pass

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_terminal_accepts_configured_dev_origin_through_proxy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            TERMINAL_ROUTE,
            headers=_websocket_headers("http://localhost:5175"),
        ) as websocket,
    ):
        websocket.send_bytes(b"exit\n")
        _receive_until_disconnect(websocket, needle=b"exit")


def test_terminal_accepts_same_origin_loopback_ip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            TERMINAL_ROUTE,
            headers=_websocket_headers(
                "http://127.0.0.1:8788",
                host="127.0.0.1:8788",
            ),
        ) as websocket,
    ):
        websocket.send_bytes(b"exit\n")
        _receive_until_disconnect(websocket, needle=b"exit")


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("SHELL", _shell_for_tests())
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(tmp_path))
    return TestClient(create_app())


def _websocket_headers(origin: str, *, host: str = "localhost:8788") -> dict[str, str]:
    return {"Origin": origin, "Host": host}


def _python_interrupt_probe_command() -> bytes:
    script = (
        "import time\n"
        'print("TM_READY", flush=True)\n'
        "try:\n"
        "    time.sleep(30)\n"
        "except KeyboardInterrupt:\n"
        '    print("TM_INTERRUPTED", flush=True)\n'
    )
    return f"python -c 'exec(bytes.fromhex(\"{script.encode().hex()}\").decode())'\n".encode()


def _read_pty_until(fd: int, *, needle: bytes, timeout_s: float = 5.0) -> bytes:
    deadline = time.monotonic() + timeout_s
    chunks = bytearray()
    while time.monotonic() < deadline:
        timeout = min(0.05, max(0.0, deadline - time.monotonic()))
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            continue

        try:
            chunk = os.read(fd, terminal.PTY_READ_CHUNK_SIZE)
        except OSError as exc:
            if exc.errno == errno.EIO:
                break
            raise
        if not chunk:
            break

        chunks.extend(chunk)
        if needle in chunks:
            break

    return bytes(chunks)


def _shell_for_tests() -> str:
    for candidate in ("/bin/sh", "/bin/bash", "/bin/zsh"):
        if Path(candidate).exists():
            return candidate
    pytest.fail("no shell available for terminal websocket tests")


def _receive_until_disconnect(websocket: WebSocketTestSession, *, needle: bytes) -> bytes:
    chunks = bytearray()
    for _ in range(50):
        try:
            chunks.extend(websocket.receive_bytes())
        except WebSocketDisconnect:
            break
        if needle in chunks:
            return bytes(chunks)
    return bytes(chunks)


def _wait_until(predicate: Callable[[], bool], *, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("condition did not become true before timeout")
