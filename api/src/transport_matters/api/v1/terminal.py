"""WebSocket backed terminal pane API."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query, WebSocket, WebSocketException, status

from transport_matters import pty_session
from transport_matters.api.v1 import terminal_bridge
from transport_matters.config import get_settings

if TYPE_CHECKING:
    from transport_matters.config import Settings


CHILD_EXIT_TIMEOUT_S = pty_session.CHILD_EXIT_TIMEOUT_S
DEFAULT_COLS = terminal_bridge.DEFAULT_COLS
DEFAULT_ROWS = terminal_bridge.DEFAULT_ROWS
MAX_COLS = terminal_bridge.MAX_COLS
MAX_ROWS = terminal_bridge.MAX_ROWS
PTY_READ_CHUNK_SIZE = terminal_bridge.PTY_READ_CHUNK_SIZE
TerminalControlError = terminal_bridge.TerminalControlError
TerminalPty = pty_session.TerminalPty
_close_fd = pty_session.close_fd
_close_terminal_master = pty_session.close_terminal_master
_close_websocket_if_connected = terminal_bridge.close_websocket_if_connected
_normalized_origin = terminal_bridge.normalize_origin
_origin_allowed = terminal_bridge.origin_allowed
_parse_control_frame = terminal_bridge.parse_control_frame
_prepare_terminal_child = pty_session.prepare_terminal_child
_receive_websocket_input = terminal_bridge.receive_websocket_input
_request_origin = terminal_bridge.request_origin_from_websocket
_send_pty_output = terminal_bridge.send_pty_output
_set_winsize = pty_session.set_winsize
_terminate_process_group = pty_session.terminate_process_group
_terminate_terminal_pty = pty_session.terminate_terminal_pty
_trusted_loopback_host = terminal_bridge.trusted_loopback_host
_validated_dimension = terminal_bridge.validated_dimension
_write_all = pty_session.write_all
spawn_pty_process = pty_session.spawn_pty_process

__all__ = [
    "CHILD_EXIT_TIMEOUT_S",
    "DEFAULT_COLS",
    "DEFAULT_ROWS",
    "MAX_COLS",
    "MAX_ROWS",
    "PTY_READ_CHUNK_SIZE",
    "TerminalControlError",
    "TerminalPty",
    "_bridge_websocket_to_pty",
    "_close_fd",
    "_close_terminal_master",
    "_close_websocket_if_connected",
    "_normalized_origin",
    "_origin_allowed",
    "_parse_control_frame",
    "_prepare_terminal_child",
    "_receive_websocket_input",
    "_request_origin",
    "_send_pty_output",
    "_set_winsize",
    "_shell_argv",
    "_spawn_terminal_pty",
    "_terminate_process_group",
    "_terminate_terminal_pty",
    "_trusted_loopback_host",
    "_validated_dimension",
    "_workspace_root",
    "_write_all",
    "router",
    "spawn_pty_process",
    "terminal_socket",
]

router = APIRouter()


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


def _spawn_terminal_pty(*, cols: int, rows: int, cwd: Path) -> TerminalPty:
    env = os.environ.copy()
    env["TERM"] = "xterm-256color"
    return spawn_pty_process(
        argv=_shell_argv(),
        env=env,
        cwd=cwd,
        cols=cols,
        rows=rows,
    )


def _shell_argv() -> list[str]:
    shell = os.environ.get("SHELL") or "/bin/bash"
    if Path(shell).is_absolute() and os.access(shell, os.X_OK):
        return [shell]

    resolved = shutil.which(shell)
    if resolved is not None:
        return [resolved]

    return ["/bin/bash"]


async def _bridge_websocket_to_pty(websocket: WebSocket, session: TerminalPty) -> None:
    await terminal_bridge.bridge_websocket_to_pty(
        websocket,
        session,
        set_winsize_fn=_set_winsize,
    )
