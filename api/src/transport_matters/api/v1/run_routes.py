"""Managed captured run API routes."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketException
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field
from starlette.websockets import WebSocketDisconnect

from transport_matters.api.v1 import terminal_bridge
from transport_matters.captured_run import CLAUDE_CLIENT_NAME, CODEX_CLIENT_NAME
from transport_matters.config import Settings, get_settings
from transport_matters.run_manager import (
    SLOW_VIEWER_CLOSE_CODE,
    AttachedTerminal,
    AttachmentClosed,
    CapturedRunCli,
    ManagedRun,
    ManagedRunView,
    PtyChunk,
    RunFilters,
    RunManager,
    RunManagerError,
    RunNotFoundError,
    RunState,
    SpawnRun,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

RUNS_ROUTE_PREFIX = "/runs"
_CAPTURED_RUN_CLI_ALLOWLIST = frozenset({CLAUDE_CLIENT_NAME, CODEX_CLIENT_NAME})

router = APIRouter()


class ApiError(BaseModel):
    code: str
    message: str
    details: object | None = None


class TerminalSizeModel(BaseModel):
    cols: int = Field(default=terminal_bridge.DEFAULT_COLS, ge=1, le=terminal_bridge.MAX_COLS)
    rows: int = Field(default=terminal_bridge.DEFAULT_ROWS, ge=1, le=terminal_bridge.MAX_ROWS)


class CreateRunRequest(BaseModel):
    cli: str
    cwd: str | None = None
    terminal: TerminalSizeModel | None = None


class RunViewModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(serialization_alias="runId")
    cli: CapturedRunCli
    cwd: str
    storage_dir: str = Field(serialization_alias="storageDir")
    proxy_port: int = Field(serialization_alias="proxyPort")
    web_port: int | None = Field(default=None, serialization_alias="webPort")
    native_session_id: str | None = Field(default=None, serialization_alias="nativeSessionId")
    state: RunState
    viewer_count: int = Field(serialization_alias="viewerCount")
    created_at: str = Field(serialization_alias="createdAt")
    started_at: str = Field(serialization_alias="startedAt")
    updated_at: str = Field(serialization_alias="updatedAt")
    viewerless_since: str | None = Field(default=None, serialization_alias="viewerlessSince")
    exit_code: int | None = Field(default=None, serialization_alias="exitCode")
    stop_reason: str | None = Field(default=None, serialization_alias="stopReason")
    scrollback_bytes: int = Field(serialization_alias="scrollbackBytes")
    scrollback_limit_bytes: int = Field(serialization_alias="scrollbackLimitBytes")


class CreateRunResponse(BaseModel):
    run: RunViewModel


class ListRunsResponse(BaseModel):
    runs: list[RunViewModel]


class StopRunResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(serialization_alias="runId")
    state: RunState
    stop_reason: Literal["explicit-stop"] = Field(serialization_alias="stopReason")


def create_run_manager() -> RunManager:
    return RunManager()


async def close_run_manager(app: Any) -> None:
    manager = getattr(app.state, "run_manager", None)
    if isinstance(manager, RunManager):
        await manager.close()


def get_run_manager_from_app(app: Any) -> RunManager:
    manager = getattr(app.state, "run_manager", None)
    if isinstance(manager, RunManager):
        return manager
    manager = create_run_manager()
    app.state.run_manager = manager
    return manager


def _run_manager(request: Request) -> RunManager:
    return get_run_manager_from_app(request.app)


def _api_error(code: str, message: str, details: object | None = None) -> dict[str, object]:
    payload = ApiError(code=code, message=message, details=details).model_dump(exclude_none=True)
    return cast("dict[str, object]", payload)


def _raise_api_error(
    status_code: int, code: str, message: str, details: object | None = None
) -> NoReturn:
    raise HTTPException(status_code=status_code, detail=_api_error(code, message, details))


def _http_error_from_manager(exc: RunManagerError) -> NoReturn:
    if exc.code == "invalid_cwd":
        _raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cwd", exc.message)
    if exc.code == "unsupported_cli":
        _raise_api_error(http_status.HTTP_400_BAD_REQUEST, "unsupported_cli", exc.message)
    if exc.code == "session_store_unavailable":
        _raise_api_error(
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
            "session_store_unavailable",
            exc.message,
        )
    if exc.code == "bind_conflict":
        _raise_api_error(http_status.HTTP_409_CONFLICT, "bind_conflict", exc.message)
    _raise_api_error(http_status.HTTP_500_INTERNAL_SERVER_ERROR, "launch_failed", exc.message)


def _not_found(run_id: str) -> NoReturn:
    _raise_api_error(http_status.HTTP_404_NOT_FOUND, "run_not_found", f"run not found: {run_id}")


async def require_http_origin(request: Request) -> None:
    if terminal_bridge.origin_allowed_for_request(request, get_settings()):
        return
    _raise_api_error(http_status.HTTP_403_FORBIDDEN, "origin_not_allowed", "origin not allowed")


def _validated_cli(cli: str) -> CapturedRunCli:
    if cli not in _CAPTURED_RUN_CLI_ALLOWLIST:
        _raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "unsupported_cli",
            f"unsupported captured run cli: {cli}",
        )
    return cast("CapturedRunCli", cli)


def _validated_state(state: str) -> RunState:
    try:
        return RunState(state)
    except ValueError:
        _raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_state",
            f"unsupported run state: {state}",
        )


def _validated_existing_dir(cwd: str) -> Path:
    working_dir = Path(cwd).expanduser()
    if not working_dir.is_absolute():
        _raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cwd", "cwd must be absolute")
    if not working_dir.exists():
        _raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_cwd",
            f"cwd does not exist: {working_dir}",
        )
    if not working_dir.is_dir():
        _raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_cwd",
            f"cwd is not a directory: {working_dir}",
        )
    return working_dir.resolve()


def _request_cwd(cwd: str | None, settings: Settings) -> Path | None:
    if cwd is not None:
        return _validated_existing_dir(cwd)
    if settings.cwd is None:
        return None
    return _validated_existing_dir(str(settings.cwd))


def _spawn_request(body: CreateRunRequest, settings: Settings) -> SpawnRun:
    terminal = body.terminal or TerminalSizeModel()
    return SpawnRun(
        cli=_validated_cli(body.cli),
        cwd=_request_cwd(body.cwd, settings),
        cols=terminal.cols,
        rows=terminal.rows,
        passthrough=settings.default_client_passthrough,
        home_dir=settings.agent_home_dir,
        debug=settings.debug,
    )


def run_view_model(view: ManagedRunView) -> RunViewModel:
    return RunViewModel(
        run_id=view.run_id,
        cli=view.cli,
        cwd=str(view.cwd),
        storage_dir=str(view.storage_dir),
        proxy_port=view.proxy_port,
        web_port=view.web_port,
        native_session_id=view.native_session_id,
        state=view.state,
        viewer_count=view.viewer_count,
        created_at=view.created_at.isoformat(),
        started_at=view.started_at.isoformat(),
        updated_at=view.updated_at.isoformat(),
        viewerless_since=(view.viewerless_since.isoformat() if view.viewerless_since else None),
        exit_code=view.exit_code,
        stop_reason=view.stop_reason,
        scrollback_bytes=view.scrollback_bytes,
        scrollback_limit_bytes=view.scrollback_limit_bytes,
    )


def run_view_payload(view: ManagedRunView) -> dict[str, object]:
    return cast(
        "dict[str, object]",
        run_view_model(view).model_dump(mode="json", by_alias=True, exclude_none=True),
    )


def _response_payload(response: BaseModel) -> dict[str, object]:
    return cast(
        "dict[str, object]",
        response.model_dump(mode="json", by_alias=True, exclude_none=True),
    )


@router.post(RUNS_ROUTE_PREFIX, status_code=http_status.HTTP_201_CREATED)
async def create_run(
    body: CreateRunRequest,
    request: Request,
    _origin: None = Depends(require_http_origin),
) -> dict[str, object]:
    manager = _run_manager(request)
    try:
        run = await manager.spawn(_spawn_request(body, get_settings()))
    except RunManagerError as exc:
        _http_error_from_manager(exc)
    return _response_payload(CreateRunResponse(run=run_view_model(run.view())))


@router.get(RUNS_ROUTE_PREFIX)
async def list_runs(
    request: Request,
    cli: str | None = Query(default=None),
    cwd: str | None = Query(default=None),
    state: str | None = Query(default=None),
) -> dict[str, object]:
    filters = RunFilters(
        cli=_validated_cli(cli) if cli is not None else None,
        cwd=_validated_existing_dir(cwd) if cwd is not None else None,
        states=frozenset({_validated_state(state)}) if state is not None else None,
    )
    manager = _run_manager(request)
    return _response_payload(
        ListRunsResponse(runs=[run_view_model(view) for view in manager.list(filters)])
    )


@router.delete(RUNS_ROUTE_PREFIX + "/{run_id}")
async def stop_run(
    run_id: str,
    request: Request,
    _origin: None = Depends(require_http_origin),
) -> dict[str, object]:
    manager = _run_manager(request)
    try:
        view = await manager.stop(run_id, reason="explicit-stop")
    except RunNotFoundError:
        _not_found(run_id)
    return _response_payload(
        StopRunResponse(run_id=view.run_id, state=view.state, stop_reason="explicit-stop")
    )


@router.websocket(RUNS_ROUTE_PREFIX + "/{run_id}/terminal")
async def run_terminal_socket(
    websocket: WebSocket,
    run_id: str,
    cols: int = Query(default=terminal_bridge.DEFAULT_COLS, ge=1, le=terminal_bridge.MAX_COLS),
    rows: int = Query(default=terminal_bridge.DEFAULT_ROWS, ge=1, le=terminal_bridge.MAX_ROWS),
) -> None:
    settings = get_settings()
    if not terminal_bridge.origin_allowed(websocket, settings):
        raise WebSocketException(
            code=http_status.WS_1008_POLICY_VIOLATION,
            reason="origin not allowed",
        )

    await websocket.accept()
    manager = get_run_manager_from_app(websocket.scope["app"])
    try:
        await bridge_attached_run_terminal(
            websocket,
            manager=manager,
            run_id=run_id,
            cols=cols,
            rows=rows,
            ready_frame=run_terminal_ready_frame,
            include_scrollback_end=True,
        )
    except RunNotFoundError:
        await send_run_error_and_close(
            websocket, code="run_not_found", message=f"run not found: {run_id}"
        )
    except RunManagerError as exc:
        code = exc.code if exc.code == "run_not_attachable" else "launch_failed"
        await send_run_error_and_close(websocket, code=code, message=exc.message)
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError:
        return


def run_terminal_ready_frame(run: ManagedRun, attached: AttachedTerminal) -> dict[str, object]:
    replayed_bytes = sum(len(chunk.data) for chunk in attached.scrollback)
    return {
        "type": "run.terminal.ready",
        "run": run_view_payload(run.view()),
        "terminal": {
            "cols": attached.attachment.cols,
            "rows": attached.attachment.rows,
        },
        "scrollback": {
            "replayedBytes": replayed_bytes,
            "truncated": run.scrollback.truncated,
        },
    }


async def bridge_attached_run_terminal(
    websocket: WebSocket,
    *,
    manager: RunManager,
    run_id: str,
    cols: int,
    rows: int,
    ready_frame: Callable[[ManagedRun, AttachedTerminal], dict[str, object]],
    include_scrollback_end: bool,
) -> None:
    attached = manager.attach(run_id, cols=cols, rows=rows)
    attachment_id = attached.attachment.attachment_id
    run = manager.get(run_id)
    send_lock = asyncio.Lock()

    async def send_json(payload: dict[str, object]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def send_bytes(payload: bytes) -> None:
        async with send_lock:
            await websocket.send_bytes(payload)

    async def invalid_control_frame() -> None:
        await send_json(
            {
                "type": "run.error",
                "code": "invalid_terminal_control_frame",
                "message": "invalid terminal control frame",
            }
        )

    output_task: asyncio.Task[None] | None = None
    input_task: asyncio.Task[None] | None = None
    try:
        await send_json(ready_frame(run, attached))
        for chunk in attached.scrollback:
            await send_bytes(chunk.data)
        if include_scrollback_end:
            await send_json({"type": "run.terminal.scrollback-end"})

        output_task = asyncio.create_task(
            _send_attachment_output(
                websocket,
                attached.attachment.queue,
                send_json=send_json,
                send_bytes=send_bytes,
            )
        )
        input_task = asyncio.create_task(
            terminal_bridge.receive_websocket_input(
                websocket,
                run.terminal.master_fd,
                on_invalid_control_frame=invalid_control_frame,
            )
        )
        done, pending = await asyncio.wait(
            {output_task, input_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
                task.result()
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    finally:
        for pending_task in (output_task, input_task):
            if pending_task is not None:
                pending_task.cancel()
        await asyncio.gather(
            *(task for task in (output_task, input_task) if task is not None),
            return_exceptions=True,
        )
        with contextlib.suppress(RunNotFoundError):
            manager.detach(run_id, attachment_id)


async def _send_attachment_output(
    websocket: WebSocket,
    output_queue: asyncio.Queue[PtyChunk | AttachmentClosed],
    *,
    send_json: Callable[[dict[str, object]], Awaitable[None]],
    send_bytes: Callable[[bytes], Awaitable[None]],
) -> None:
    while True:
        item = await output_queue.get()
        if isinstance(item, PtyChunk):
            await send_bytes(item.data)
            continue
        if item.code == SLOW_VIEWER_CLOSE_CODE:
            await send_json(
                {
                    "type": "run.error",
                    "code": "attachment_overloaded",
                    "message": item.message,
                }
            )
        await terminal_bridge.close_websocket_if_connected(websocket)
        return


async def send_run_error_and_close(websocket: WebSocket, *, code: str, message: str) -> None:
    await websocket.send_json({"type": "run.error", "code": code, "message": message})
    await terminal_bridge.close_websocket_if_connected(
        websocket,
        code=http_status.WS_1008_POLICY_VIOLATION,
        reason=code,
    )
