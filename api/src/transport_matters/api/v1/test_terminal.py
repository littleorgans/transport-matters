from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from transport_matters.api.v1 import terminal
from transport_matters.main import create_app

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.testclient import WebSocketTestSession


ALLOWED_ORIGIN = "http://testserver"


def test_terminal_runs_shell_command(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        client.websocket_connect(
            "/api/v1/terminal?cols=80&rows=24",
            headers={"Origin": ALLOWED_ORIGIN},
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
            "/api/v1/terminal",
            headers={"Origin": ALLOWED_ORIGIN},
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
            "/api/v1/terminal",
            headers={"Origin": ALLOWED_ORIGIN},
        ),
    ):
        assert sessions

    session = sessions[0]
    _wait_until(lambda: session.process.poll() is not None and session.closed)

    assert session.process.poll() is not None
    with pytest.raises(OSError):
        os.fstat(session.master_fd)


def test_terminal_rejects_origin_mismatch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client = _client(monkeypatch, tmp_path)

    with (
        client,
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/api/v1/terminal",
            headers={"Origin": "http://evil.test"},
        ),
    ):
        pass

    assert exc_info.value.code == status.WS_1008_POLICY_VIOLATION


def test_terminal_accepts_configured_dev_origin_through_proxy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _client(monkeypatch, tmp_path, base_url="http://localhost:8788")

    with (
        client,
        client.websocket_connect(
            "/api/v1/terminal",
            headers={"Origin": "http://localhost:5175"},
        ) as websocket,
    ):
        websocket.send_bytes(b"exit\n")
        _receive_until_disconnect(websocket, needle=b"exit")


def _client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, base_url: str = "http://testserver"
) -> TestClient:
    monkeypatch.setenv("SHELL", _shell_for_tests())
    monkeypatch.setenv("TRANSPORT_MATTERS_CWD", str(tmp_path))
    return TestClient(create_app(), base_url=base_url)


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
