"""Captured Claude terminal WebSocket API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import typer
from fastapi import APIRouter, Query, WebSocket, WebSocketException, status
from starlette.websockets import WebSocketDisconnect

from transport_matters.api.v1 import terminal_bridge
from transport_matters.captured_run import (
    CLAUDE_CLIENT_NAME,
    CLAUDE_UPSTREAM_DEFAULT,
    CapturedRunBindConflict,
    CapturedRunRequest,
    default_claude_run_dependencies,
    prepare_captured_run,
)
from transport_matters.config import get_settings

if TYPE_CHECKING:
    from collections.abc import Callable

    from transport_matters.api.v1.terminal_bridge import TerminalPty
    from transport_matters.captured_run import CapturedRunLease, CapturedRunSpawnSpec
    from transport_matters.config import Settings

CapturedRunErrorCode = Literal[
    "origin_not_allowed",
    "invalid_terminal_control_frame",
    "session_store_unavailable",
    "launch_failed",
    "bind_conflict",
]

CAPTURED_CLAUDE_TERMINAL_ROUTE = "/captured-runs/claude/terminal"
_CLOSE_REASON_LIMIT_BYTES = 123
_CAPTURED_TERMINAL_INSTALL_SIGNAL_HANDLERS = False

logger = logging.getLogger(__name__)
router = APIRouter()

_bridge_websocket_to_pty = terminal_bridge.bridge_websocket_to_pty
spawn_pty_process = terminal_bridge.spawn_pty_process


class CapturedTerminalLaunchError(RuntimeError):
    def __init__(self, code: CapturedRunErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@router.websocket(CAPTURED_CLAUDE_TERMINAL_ROUTE)
async def captured_claude_terminal_socket(
    websocket: WebSocket,
    cols: int = Query(default=terminal_bridge.DEFAULT_COLS, ge=1, le=terminal_bridge.MAX_COLS),
    rows: int = Query(default=terminal_bridge.DEFAULT_ROWS, ge=1, le=terminal_bridge.MAX_ROWS),
    cwd: str | None = Query(default=None),
) -> None:
    """Bridge one WebSocket to one captured Claude Code PTY run."""
    settings = get_settings()
    if not terminal_bridge.origin_allowed(websocket, settings):
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="origin not allowed",
        )

    await websocket.accept()
    lease: CapturedRunLease | None = None
    terminal_session: TerminalPty | None = None
    try:
        spawn_spec, lease = await asyncio.to_thread(
            _prepare_captured_claude_run,
            cwd=cwd,
            settings=settings,
        )
        client = spawn_spec.client
        if client is None:
            raise CapturedTerminalLaunchError(
                "launch_failed",
                "captured Claude launch did not produce a client process",
            )

        if not await _send_json_if_connected(websocket, _ready_frame(spawn_spec)):
            return
        terminal_session = spawn_pty_process(
            argv=client.argv,
            env=client.env,
            cwd=client.cwd,
            cols=cols,
            rows=rows,
        )
        await _bridge_websocket_to_pty(websocket, terminal_session)
    except CapturedTerminalLaunchError as exc:
        await _send_error_and_close(websocket, code=exc.code, message=exc.message)
    except CapturedRunBindConflict as exc:
        await _send_error_and_close(websocket, code="bind_conflict", message=str(exc))
    except WebSocketDisconnect:
        pass
    except typer.Exit as exc:
        await _send_error_and_close(
            websocket,
            code="launch_failed",
            message=f"captured Claude launch failed with exit code {exc.exit_code}",
        )
    except Exception as exc:
        logger.exception("captured Claude terminal launch failed")
        await _send_error_and_close(websocket, code="launch_failed", message=str(exc))
    finally:
        await _teardown_captured_terminal_run_async(
            terminal_session,
            lease,
            install_signal_handlers=_CAPTURED_TERMINAL_INSTALL_SIGNAL_HANDLERS,
        )


def _prepare_captured_claude_run(
    *,
    cwd: str | None,
    settings: Settings,
) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
    dependencies = default_claude_run_dependencies()
    store_error = dependencies.check_session_store()
    if store_error is not None:
        raise CapturedTerminalLaunchError("session_store_unavailable", store_error)

    working_dir = _query_working_dir(cwd, settings)
    return prepare_captured_run(
        CapturedRunRequest(
            client_name=CLAUDE_CLIENT_NAME,
            passthrough=(),
            directory=working_dir,
            proxy_port=None,
            web_port=settings.web_port,
            upstream=CLAUDE_UPSTREAM_DEFAULT,
            storage_dir=None,
            home_dir=settings.agent_home_dir,
            client_bin=None,
            client_disabled=False,
            no_system_prompt=False,
            debug=settings.debug,
        ),
        require_addon=dependencies.require_addon,
        resolve_mitmdump=dependencies.resolve_mitmdump,
        which=dependencies.which,
        port_in_use=_port_in_use_except_current_web(settings, dependencies.port_in_use),
        allocate_port_pair=dependencies.allocate_port_pair,
        inject_system_prompt=dependencies.inject_system_prompt,
        user_supplied_system_prompt=dependencies.user_supplied_system_prompt,
        install_signal_handlers=_CAPTURED_TERMINAL_INSTALL_SIGNAL_HANDLERS,
    )


def _query_working_dir(cwd: str | None, settings: Settings) -> Path:
    if cwd is None:
        return (settings.cwd or Path.cwd()).resolve()

    working_dir = Path(cwd).expanduser()
    if not working_dir.is_absolute():
        raise CapturedTerminalLaunchError("launch_failed", "cwd must be an absolute path")
    return working_dir


def _port_in_use_except_current_web(
    settings: Settings,
    port_in_use: Callable[[int], bool],
) -> Callable[[int], bool]:
    def current_web_port_aware_check(port: int) -> bool:
        if port == settings.web_port:
            return False
        return port_in_use(port)

    return current_web_port_aware_check


def _ready_frame(spawn_spec: CapturedRunSpawnSpec) -> dict[str, object]:
    frame: dict[str, object] = {
        "type": "captured-run.ready",
        "runId": spawn_spec.run_id,
        "cwd": str(spawn_spec.working_dir),
        "storageDir": str(spawn_spec.storage_dir),
        "proxyPort": spawn_spec.proxy_port,
        "webPort": spawn_spec.web_port,
        "cli": CLAUDE_CLIENT_NAME,
    }
    if spawn_spec.managed_session is not None:
        frame["nativeSessionId"] = spawn_spec.managed_session.native_session_id
    return frame


async def _send_error_and_close(
    websocket: WebSocket,
    *,
    code: CapturedRunErrorCode,
    message: str,
) -> None:
    await _send_json_if_connected(
        websocket,
        {
            "type": "captured-run.error",
            "code": code,
            "message": message,
        },
    )
    await terminal_bridge.close_websocket_if_connected(
        websocket,
        code=status.WS_1011_INTERNAL_ERROR,
        reason=_bounded_close_reason(code, message),
    )


async def _send_json_if_connected(websocket: WebSocket, payload: dict[str, object]) -> bool:
    if not terminal_bridge.websocket_connected(websocket):
        return False
    with contextlib.suppress(RuntimeError, WebSocketDisconnect):
        await websocket.send_json(payload)
        return True
    return False


async def _teardown_captured_terminal_run_async(
    terminal_session: TerminalPty | None,
    lease: CapturedRunLease | None,
    *,
    install_signal_handlers: bool,
) -> None:
    if install_signal_handlers:
        _teardown_captured_terminal_run(terminal_session, lease)
        return
    await asyncio.to_thread(_teardown_captured_terminal_run, terminal_session, lease)


def _teardown_captured_terminal_run(
    terminal_session: TerminalPty | None,
    lease: CapturedRunLease | None,
) -> None:
    if terminal_session is not None:
        terminal_bridge.terminate_terminal_pty(terminal_session)
    if lease is not None:
        lease.close()


def _bounded_close_reason(code: str, message: str) -> str:
    reason = f"{code}: {message}".replace("\n", " ")
    encoded = reason.encode()
    if len(encoded) <= _CLOSE_REASON_LIMIT_BYTES:
        return reason
    return encoded[: _CLOSE_REASON_LIMIT_BYTES - 3].decode(errors="ignore") + "..."
