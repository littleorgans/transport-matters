"""Shared WebSocket to PTY bridge primitives."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import logging
import os
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from fastapi import Request, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState

from transport_matters.pty_session import (
    CHILD_EXIT_TIMEOUT_S,
    TerminalPty,
    WinsizeSetter,
    close_fd,
    close_terminal_master,
    prepare_terminal_child,
    set_winsize,
    spawn_pty_process,
    terminate_process_group,
    terminate_terminal_pty,
    write_all,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from transport_matters.config import Settings

logger = logging.getLogger(__name__)

DEFAULT_COLS = 80
DEFAULT_ROWS = 24
MAX_COLS = 500
MAX_ROWS = 200
PTY_READ_CHUNK_SIZE = 8192
_TERMINAL_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_WinsizeSetter = WinsizeSetter

__all__ = [
    "CHILD_EXIT_TIMEOUT_S",
    "DEFAULT_COLS",
    "DEFAULT_ROWS",
    "MAX_COLS",
    "MAX_ROWS",
    "PTY_READ_CHUNK_SIZE",
    "TerminalControlError",
    "TerminalPty",
    "_WinsizeSetter",
    "bridge_websocket_to_pty",
    "close_fd",
    "close_terminal_master",
    "close_websocket_if_connected",
    "normalize_origin",
    "origin_allowed",
    "origin_allowed_for_request",
    "origin_allowed_from_headers",
    "parse_control_frame",
    "prepare_terminal_child",
    "receive_websocket_input",
    "request_origin_from_headers",
    "request_origin_from_request",
    "request_origin_from_websocket",
    "send_pty_output",
    "set_winsize",
    "spawn_pty_process",
    "terminate_process_group",
    "terminate_terminal_pty",
    "trusted_loopback_host",
    "validated_dimension",
    "websocket_connected",
    "write_all",
]


class TerminalControlError(ValueError):
    """Raised when a terminal text control frame is invalid."""


def origin_allowed(websocket: WebSocket, settings: Settings) -> bool:
    return origin_allowed_from_headers(
        websocket.headers,
        scheme="https" if websocket.url.scheme == "wss" else "http",
        settings=settings,
    )


def origin_allowed_for_request(request: Request, settings: Settings) -> bool:
    return origin_allowed_from_headers(
        request.headers, scheme=request.url.scheme, settings=settings
    )


def origin_allowed_from_headers(
    headers: Mapping[str, str], *, scheme: str, settings: Settings
) -> bool:
    request_origin = request_origin_from_headers(headers, scheme=scheme, settings=settings)
    if request_origin is None:
        return False

    normalized_origin = normalize_origin(headers.get("origin"))
    if normalized_origin is None:
        return False

    configured_origins = {
        configured
        for configured in (normalize_origin(value) for value in settings.cors_origins)
        if configured is not None
    }
    if normalized_origin in configured_origins:
        return True

    return normalized_origin == request_origin


def normalize_origin(value: str | None) -> str | None:
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


def request_origin_from_websocket(websocket: WebSocket, settings: Settings) -> str | None:
    return request_origin_from_headers(
        websocket.headers,
        scheme="https" if websocket.url.scheme == "wss" else "http",
        settings=settings,
    )


def request_origin_from_request(request: Request, settings: Settings) -> str | None:
    return request_origin_from_headers(
        request.headers, scheme=request.url.scheme, settings=settings
    )


def request_origin_from_headers(
    headers: Mapping[str, str], *, scheme: str, settings: Settings
) -> str | None:
    host = trusted_loopback_host(
        headers.get("host"),
        allowed_port=settings.web_port,
    )
    if not host:
        return None

    return f"{scheme}://{host}"


def trusted_loopback_host(value: str | None, *, allowed_port: int) -> str | None:
    if not value:
        return None

    try:
        parsed = urlsplit(f"//{value}")
        port = parsed.port
    except ValueError:
        return None

    if (
        parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
        or port != allowed_port
    ):
        return None

    hostname = parsed.hostname.lower() if parsed.hostname else None
    if hostname not in _TERMINAL_LOOPBACK_HOSTS:
        return None

    return parsed.netloc.lower()


async def bridge_websocket_to_pty(
    websocket: WebSocket,
    session: TerminalPty,
    *,
    set_winsize_fn: _WinsizeSetter | None = None,
) -> None:
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
    output_task = asyncio.create_task(send_pty_output(websocket, output_queue))
    input_task = asyncio.create_task(
        receive_websocket_input(
            websocket,
            session.master_fd,
            set_winsize_fn=set_winsize if set_winsize_fn is None else set_winsize_fn,
        )
    )
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


async def send_pty_output(websocket: WebSocket, output_queue: asyncio.Queue[bytes | None]) -> None:
    while True:
        data = await output_queue.get()
        if data is None:
            await close_websocket_if_connected(websocket)
            return
        await websocket.send_bytes(data)


async def receive_websocket_input(
    websocket: WebSocket,
    master_fd: int,
    *,
    set_winsize_fn: _WinsizeSetter = set_winsize,
    on_invalid_control_frame: Callable[[], Awaitable[None]] | None = None,
) -> None:
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
                await asyncio.to_thread(write_all, master_fd, payload)
            continue

        text = message.get("text")
        if text is not None:
            try:
                cols, rows = parse_control_frame(text)
            except TerminalControlError:
                if on_invalid_control_frame is not None:
                    await on_invalid_control_frame()
                await close_websocket_if_connected(
                    websocket,
                    code=status.WS_1008_POLICY_VIOLATION,
                    reason="invalid terminal control frame",
                )
                return
            set_winsize_fn(master_fd, cols=cols, rows=rows)


def parse_control_frame(text: str) -> tuple[int, int]:
    try:
        frame = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TerminalControlError("control frame is not valid JSON") from exc

    if not isinstance(frame, dict) or frame.get("type") != "resize":
        raise TerminalControlError("control frame type is invalid")

    cols = validated_dimension(frame.get("cols"), name="cols", maximum=MAX_COLS)
    rows = validated_dimension(frame.get("rows"), name="rows", maximum=MAX_ROWS)
    return cols, rows


def validated_dimension(value: object, *, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TerminalControlError(f"{name} must be an integer")
    if value < 1 or value > maximum:
        raise TerminalControlError(f"{name} is out of range")
    return value


async def close_websocket_if_connected(
    websocket: WebSocket, *, code: int = status.WS_1000_NORMAL_CLOSURE, reason: str = ""
) -> None:
    if websocket_connected(websocket):
        with contextlib.suppress(WebSocketDisconnect, RuntimeError):
            await websocket.close(code=code, reason=reason)


def websocket_connected(websocket: WebSocket) -> bool:
    return (
        websocket.application_state == WebSocketState.CONNECTED
        and websocket.client_state == WebSocketState.CONNECTED
    )
