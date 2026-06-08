"""WebSocket backed terminal pane API."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import fcntl
import json
import logging
import os
import pty
import shutil
import signal
import struct
import subprocess
import termios
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, WebSocketException, status
from starlette.websockets import WebSocketState

from transport_matters.config import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

DEFAULT_COLS = 80
DEFAULT_ROWS = 24
MAX_COLS = 500
MAX_ROWS = 200
PTY_READ_CHUNK_SIZE = 8192
CHILD_EXIT_TIMEOUT_S = 1.0


class TerminalControlError(ValueError):
    """Raised when a terminal text control frame is invalid."""


@dataclass(slots=True)
class TerminalPty:
    """One child shell process attached to one PTY master."""

    master_fd: int
    process: subprocess.Popen[bytes]
    closed: bool = False


@router.websocket("/terminal")
async def terminal_socket(
    websocket: WebSocket,
    cols: int = Query(default=DEFAULT_COLS, ge=1, le=MAX_COLS),
    rows: int = Query(default=DEFAULT_ROWS, ge=1, le=MAX_ROWS),
) -> None:
    """Bridge one WebSocket to one interactive local shell process."""
    settings = get_settings()
    if not _origin_allowed(websocket, settings):
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="origin not allowed",
        )

    await websocket.accept()
    session = _spawn_terminal_pty(cols=cols, rows=rows, cwd=_workspace_root(settings))
    try:
        await _bridge_websocket_to_pty(websocket, session)
    finally:
        await asyncio.to_thread(_terminate_terminal_pty, session)


def _workspace_root(settings: Settings) -> Path:
    return (settings.cwd or Path.cwd()).resolve()


def _origin_allowed(websocket: WebSocket, settings: Settings) -> bool:
    origin = websocket.headers.get("origin")
    normalized_origin = _normalized_origin(origin)
    if normalized_origin is None:
        return False

    configured_origins = {
        configured
        for configured in (_normalized_origin(value) for value in settings.cors_origins)
        if configured is not None
    }
    if normalized_origin in configured_origins:
        return True

    return normalized_origin == _request_origin(websocket)


def _normalized_origin(value: str | None) -> str | None:
    if not value:
        return None

    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if not parsed.netloc:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _request_origin(websocket: WebSocket) -> str | None:
    host = websocket.headers.get("host")
    if not host:
        return None

    scheme = "https" if websocket.url.scheme == "wss" else "http"
    return f"{scheme}://{host.lower()}"


def _spawn_terminal_pty(*, cols: int, rows: int, cwd: Path) -> TerminalPty:
    master_fd, slave_fd = pty.openpty()
    try:
        _set_winsize(slave_fd, cols=cols, rows=rows)
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        process = subprocess.Popen(
            _shell_argv(),
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            cwd=cwd,
            env=env,
            start_new_session=True,
            close_fds=True,
        )
    except Exception:
        _close_fd(slave_fd)
        _close_fd(master_fd)
        raise

    _close_fd(slave_fd)
    return TerminalPty(master_fd=master_fd, process=process)


def _shell_argv() -> list[str]:
    shell = os.environ.get("SHELL") or "/bin/bash"
    if Path(shell).is_absolute() and os.access(shell, os.X_OK):
        return [shell]

    resolved = shutil.which(shell)
    if resolved is not None:
        return [resolved]

    return ["/bin/bash"]


def _set_winsize(fd: int, *, cols: int, rows: int) -> None:
    packed = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)


async def _bridge_websocket_to_pty(websocket: WebSocket, session: TerminalPty) -> None:
    loop = asyncio.get_running_loop()
    output_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    def read_ready() -> None:
        try:
            data = os.read(session.master_fd, PTY_READ_CHUNK_SIZE)
        except OSError as exc:
            if exc.errno not in {errno.EIO, errno.EBADF}:
                logger.exception("terminal PTY read failed")
            loop.remove_reader(session.master_fd)
            output_queue.put_nowait(None)
            return

        if not data:
            loop.remove_reader(session.master_fd)
            output_queue.put_nowait(None)
            return

        output_queue.put_nowait(data)

    loop.add_reader(session.master_fd, read_ready)
    output_task = asyncio.create_task(_send_pty_output(websocket, output_queue))
    input_task = asyncio.create_task(_receive_websocket_input(websocket, session.master_fd))
    tasks = {output_task, input_task}
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        loop.remove_reader(session.master_fd)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _send_pty_output(websocket: WebSocket, output_queue: asyncio.Queue[bytes | None]) -> None:
    while True:
        data = await output_queue.get()
        if data is None:
            await _close_websocket_if_connected(websocket)
            return
        await websocket.send_bytes(data)


async def _receive_websocket_input(websocket: WebSocket, master_fd: int) -> None:
    while True:
        message = await websocket.receive()
        message_type = message["type"]
        if message_type == "websocket.disconnect":
            return
        if message_type != "websocket.receive":
            continue

        payload = message.get("bytes")
        if payload is not None:
            if payload:
                await asyncio.to_thread(_write_all, master_fd, payload)
            continue

        text = message.get("text")
        if text is not None:
            try:
                cols, rows = _parse_control_frame(text)
            except TerminalControlError:
                await _close_websocket_if_connected(
                    websocket,
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="invalid terminal control frame",
                )
                return
            _set_winsize(master_fd, cols=cols, rows=rows)


def _parse_control_frame(text: str) -> tuple[int, int]:
    try:
        frame = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TerminalControlError("control frame is not valid JSON") from exc

    if not isinstance(frame, dict) or frame.get("type") != "resize":
        raise TerminalControlError("control frame type is invalid")

    cols = _validated_dimension(frame.get("cols"), name="cols", maximum=MAX_COLS)
    rows = _validated_dimension(frame.get("rows"), name="rows", maximum=MAX_ROWS)
    return cols, rows


def _validated_dimension(value: object, *, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TerminalControlError(f"{name} must be an integer")
    if value < 1 or value > maximum:
        raise TerminalControlError(f"{name} is out of range")
    return value


def _write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        try:
            written = os.write(fd, data[offset:])
        except OSError as exc:
            if exc.errno in {errno.EIO, errno.EBADF}:
                return
            raise
        if written <= 0:
            raise RuntimeError("terminal PTY write returned no progress")
        offset += written


async def _close_websocket_if_connected(
    websocket: WebSocket, *, code: int = status.WS_1000_NORMAL_CLOSURE, reason: str = ""
) -> None:
    if (
        websocket.application_state == WebSocketState.CONNECTED
        and websocket.client_state == WebSocketState.CONNECTED
    ):
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await websocket.close(code=code, reason=reason)


def _terminate_terminal_pty(session: TerminalPty) -> None:
    process = session.process
    if process.poll() is None:
        _terminate_process_group(process)
    _close_terminal_master(session)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=CHILD_EXIT_TIMEOUT_S)
        return
    except subprocess.TimeoutExpired:
        pass

    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=CHILD_EXIT_TIMEOUT_S)


def _close_terminal_master(session: TerminalPty) -> None:
    if session.closed:
        return
    _close_fd(session.master_fd)
    session.closed = True


def _close_fd(fd: int) -> None:
    with contextlib.suppress(OSError):
        os.close(fd)
