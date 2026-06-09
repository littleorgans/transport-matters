"""Compatibility bridge for captured terminal WebSocket routes.

The route is kept only until B3 moves the UI to /api/runs. It delegates run
ownership to RunManager, stops the run on socket close to preserve old pane
semantics, and must not own a lease, PTY, or teardown path.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Literal, cast

from fastapi import APIRouter, Query, WebSocket, WebSocketException, status
from starlette.websockets import WebSocketDisconnect

from transport_matters.api.v1 import run_routes, terminal_bridge
from transport_matters.captured_run import CLAUDE_CLIENT_NAME, CODEX_CLIENT_NAME
from transport_matters.config import get_settings
from transport_matters.run_manager import (
    AttachedTerminal,
    CapturedRunCli,
    ManagedRun,
    RunManagerError,
    RunNotFoundError,
)

CapturedRunErrorCode = Literal[
    "origin_not_allowed",
    "invalid_terminal_control_frame",
    "session_store_unavailable",
    "launch_failed",
    "bind_conflict",
]

CAPTURED_CLAUDE_TERMINAL_ROUTE = "/captured-runs/claude/terminal"
CAPTURED_TERMINAL_ROUTE = "/captured-runs/{cli}/terminal"
_CAPTURED_RUN_CLI_ALLOWLIST = frozenset({CLAUDE_CLIENT_NAME, CODEX_CLIENT_NAME})
_CLOSE_REASON_LIMIT_BYTES = 123

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket(CAPTURED_CLAUDE_TERMINAL_ROUTE)
async def captured_claude_terminal_socket(
    websocket: WebSocket,
    cols: int = Query(default=terminal_bridge.DEFAULT_COLS, ge=1, le=terminal_bridge.MAX_COLS),
    rows: int = Query(default=terminal_bridge.DEFAULT_ROWS, ge=1, le=terminal_bridge.MAX_ROWS),
    cwd: str | None = Query(default=None),
) -> None:
    """Bridge one WebSocket to one captured Claude Code run."""
    await _captured_terminal_socket(
        websocket,
        cli=cast("CapturedRunCli", CLAUDE_CLIENT_NAME),
        cols=cols,
        rows=rows,
        cwd=cwd,
    )


@router.websocket(CAPTURED_TERMINAL_ROUTE)
async def captured_terminal_socket(
    websocket: WebSocket,
    cli: str,
    cols: int = Query(default=terminal_bridge.DEFAULT_COLS, ge=1, le=terminal_bridge.MAX_COLS),
    rows: int = Query(default=terminal_bridge.DEFAULT_ROWS, ge=1, le=terminal_bridge.MAX_ROWS),
    cwd: str | None = Query(default=None),
) -> None:
    """Bridge one WebSocket to one captured provider run."""
    await _captured_terminal_socket(
        websocket,
        cli=_validate_captured_run_cli(cli),
        cols=cols,
        rows=rows,
        cwd=cwd,
    )


async def _captured_terminal_socket(
    websocket: WebSocket,
    *,
    cli: CapturedRunCli,
    cols: int,
    rows: int,
    cwd: str | None,
) -> None:
    settings = get_settings()
    if not terminal_bridge.origin_allowed(websocket, settings):
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="origin not allowed",
        )

    await websocket.accept()
    manager = run_routes.get_run_manager_from_app(websocket.scope["app"])
    run_id: str | None = None
    try:
        run = await manager.spawn(
            run_routes.captured_spawn_request(
                cli=cli,
                cwd=cwd,
                cols=cols,
                rows=rows,
                settings=settings,
            )
        )
        run_id = run.run_id
        await run_routes.bridge_attached_run_terminal(
            websocket,
            manager=manager,
            run_id=run.run_id,
            cols=cols,
            rows=rows,
            ready_frame=_ready_frame,
            include_scrollback_end=False,
        )
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except RunManagerError as exc:
        code = _captured_error_code(exc.code)
        if code == "launch_failed":
            logger.exception("captured %s terminal launch failed", cli)
        await _send_error_and_close(websocket, code=code, message=exc.message)
    except Exception as exc:
        logger.exception("captured %s terminal bridge failed", cli)
        await _send_error_and_close(websocket, code="launch_failed", message=str(exc))
    finally:
        if run_id is not None:
            with contextlib.suppress(RunNotFoundError):
                await manager.stop(run_id, reason="explicit-stop")


def _validate_captured_run_cli(cli: str) -> CapturedRunCli:
    if cli not in _CAPTURED_RUN_CLI_ALLOWLIST:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="unsupported captured run cli",
        )
    return cast("CapturedRunCli", cli)


def _ready_frame(run: ManagedRun, _attached: AttachedTerminal) -> dict[str, object]:
    view = run.view()
    frame: dict[str, object] = {
        "type": "captured-run.ready",
        "runId": view.run_id,
        "cwd": str(view.cwd),
        "storageDir": str(view.storage_dir),
        "proxyPort": view.proxy_port,
        "cli": view.cli,
    }
    if view.web_port is not None:
        frame["webPort"] = view.web_port
    if view.native_session_id is not None:
        frame["nativeSessionId"] = view.native_session_id
    return frame


def _captured_error_code(code: str) -> CapturedRunErrorCode:
    if code == "session_store_unavailable":
        return "session_store_unavailable"
    if code == "bind_conflict":
        return "bind_conflict"
    return "launch_failed"


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
    await websocket.send_json(payload)
    return True


def _bounded_close_reason(code: str, message: str) -> str:
    reason = f"{code}: {message}"
    encoded = reason.encode("utf-8")
    if len(encoded) <= _CLOSE_REASON_LIMIT_BYTES:
        return reason
    return encoded[: _CLOSE_REASON_LIMIT_BYTES - 3].decode("utf-8", "ignore") + "..."
