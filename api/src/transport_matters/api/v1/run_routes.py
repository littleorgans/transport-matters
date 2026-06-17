"""Managed captured run API routes."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NoReturn, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketException
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field
from starlette.websockets import WebSocketDisconnect

from transport_matters.api.v1 import terminal_bridge
from transport_matters.api.v1.run_continuation import (
    ContinuationSessionNotFound,
    build_continuation_launch_fields,
)
from transport_matters.api.v1.session_store import optional_session_pool
from transport_matters.captured_run import CLAUDE_CLIENT_NAME, CODEX_CLIENT_NAME
from transport_matters.captured_run_models import CapturedRunCli
from transport_matters.config import Settings, get_settings
from transport_matters.index.sessions import synth_session_id
from transport_matters.run_manager import (
    ManagedRun,
    ManagedRunView,
    RunFilters,
    RunManager,
    RunManagerError,
    RunManagerErrorCode,
    RunNotFoundError,
    RunState,
    SpawnRun,
)
from transport_matters.run_terminal import (
    SLOW_VIEWER_CLOSE_CODE,
    AttachedTerminal,
    AttachmentClosed,
    PtyChunk,
)
from transport_matters.runtime_registry import resolve_runtime_template
from transport_matters.workspace import workspace_id

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from transport_matters.runtime_templates import RuntimeTemplateRef

RUNS_ROUTE_PREFIX = "/runs"
DEFAULT_RUNS_LIMIT = 50
MAX_RUNS_LIMIT = 100
DEFAULT_OWNER = "local"
_CAPTURED_RUN_CLI_ALLOWLIST = frozenset({CLAUDE_CLIENT_NAME, CODEX_CLIENT_NAME})
_RUN_MANAGER_HTTP_STATUS: dict[RunManagerErrorCode, int] = {
    "bind_conflict": http_status.HTTP_409_CONFLICT,
    "invalid_cwd": http_status.HTTP_400_BAD_REQUEST,
    "launch_failed": http_status.HTTP_500_INTERNAL_SERVER_ERROR,
    "proxy_start_timeout": http_status.HTTP_503_SERVICE_UNAVAILABLE,
    "run_manager_closed": http_status.HTTP_503_SERVICE_UNAVAILABLE,
    "run_not_attachable": http_status.HTTP_409_CONFLICT,
    "run_stale": http_status.HTTP_409_CONFLICT,
    "run_terminated": http_status.HTTP_409_CONFLICT,
    "session_store_unavailable": http_status.HTTP_503_SERVICE_UNAVAILABLE,
    "unsupported_cli": http_status.HTTP_400_BAD_REQUEST,
}
_CURATED_STATES = frozenset(
    {RunState.RUNNING, RunState.TERMINATING, RunState.TERMINATED, RunState.EXITED, RunState.FAILED}
)
_END_REASONS = frozenset({"explicit", "idle-timeout", "shutdown", "deploy-restart"})
PublicRunState = Literal["RUNNING", "TERMINATING", "TERMINATED", "EXITED", "FAILED"]

router = APIRouter()


class ApiError(BaseModel):
    code: str
    message: str
    details: object | None = None


class TerminalSizeModel(BaseModel):
    cols: int = Field(default=terminal_bridge.DEFAULT_COLS, ge=1, le=terminal_bridge.MAX_COLS)
    rows: int = Field(default=terminal_bridge.DEFAULT_ROWS, ge=1, le=terminal_bridge.MAX_ROWS)


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    cli: str
    cwd: str | None = None
    terminal: TerminalSizeModel | None = None
    # Bridge answers the CLI's OSC 10/11 color queries (see osc_color_responder).
    osc_color_replies: bool = Field(default=True, alias="oscColorReplies")
    continue_from_session_id: str | None = Field(default=None, alias="continueFromSessionId")
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey")
    runtime_template: str | None = Field(default=None, alias="runtimeTemplate")


class RunViewModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(serialization_alias="runId")
    workspace_id: str = Field(serialization_alias="workspaceId")
    session_id: str = Field(serialization_alias="sessionId")
    cli: CapturedRunCli
    state: PublicRunState
    end_reason: Literal["explicit", "idle-timeout", "shutdown", "deploy-restart"] | None = Field(
        default=None, serialization_alias="endReason"
    )
    error: str | None = None
    created_at: str = Field(serialization_alias="createdAt")


class CreateRunResponse(BaseModel):
    run: RunViewModel


class ListRunsResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[RunViewModel]
    next_cursor: str | None = Field(default=None, serialization_alias="nextCursor")


class TerminateRunResponse(BaseModel):
    run: RunViewModel


def create_run_manager(shared_proxy_manager: Any | None = None) -> RunManager:
    settings = get_settings()
    return RunManager(
        spawn_concurrency=settings.captured_run_spawn_concurrency,
        shared_proxy_manager=shared_proxy_manager,
    )


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
    status_code = _RUN_MANAGER_HTTP_STATUS.get(exc.code)
    if status_code is None:
        _raise_api_error(
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            "unmapped_run_manager_error",
            "unmapped run manager error",
            {"code": exc.code},
        )
    _raise_api_error(status_code, exc.code, exc.message)


def _not_found(run_id: str) -> NoReturn:
    _raise_api_error(http_status.HTTP_404_NOT_FOUND, "run_not_found", f"run not found: {run_id}")


def _session_not_found(session_id: str) -> NoReturn:
    _raise_api_error(
        http_status.HTTP_404_NOT_FOUND,
        "session_not_found",
        f"session {session_id!r} was not found",
    )


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
        parsed = RunState(state)
    except ValueError:
        _raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_request",
            f"unsupported run state: {state}",
        )
    if parsed not in _CURATED_STATES:
        _raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_request",
            f"unsupported run state: {state}",
        )
    return parsed


def _cursor_filter_key(state: str | None) -> dict[str, str | None]:
    return {"state": state}


def _encode_cursor(offset: int, *, filters: dict[str, str | None]) -> str:
    raw = json.dumps({"offset": offset, "filters": filters}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, *, filters: dict[str, str | None]) -> int:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except binascii.Error, UnicodeDecodeError, ValueError, json.JSONDecodeError:
        _raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    if not isinstance(payload, dict):
        _raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    if payload.get("filters") != filters:
        _raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_cursor",
            "cursor does not match the active filters",
        )
    offset = payload.get("offset")
    if not isinstance(offset, int) or offset < 0:
        _raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    return offset


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


def _required_non_empty(value: str | None, *, field_name: str) -> str:
    if value is None or value.strip() == "":
        _raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_request",
            f"{field_name} is required",
        )
    return value


async def _launch_fields(
    body: CreateRunRequest, *, request: Request, owner: str
) -> dict[str, object]:
    if body.idempotency_key is not None:
        _required_non_empty(body.idempotency_key, field_name="idempotencyKey")
    parent_session_id = body.continue_from_session_id
    if parent_session_id is None:
        return {}
    parent_session_id = _required_non_empty(parent_session_id, field_name="continueFromSessionId")
    _required_non_empty(body.idempotency_key, field_name="idempotencyKey")
    pool = optional_session_pool(request)
    if pool is None:
        _raise_api_error(
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
            "session_store_unavailable",
            "session store unavailable",
        )
    try:
        continuation = await build_continuation_launch_fields(
            pool, parent_session_id=parent_session_id, owner=owner
        )
    except ContinuationSessionNotFound:
        _session_not_found(parent_session_id)
    return continuation.fields


def _runtime_template_ref(body: CreateRunRequest, cli: CapturedRunCli) -> RuntimeTemplateRef | None:
    name = body.runtime_template
    if name is None or name.strip() == "":
        return None
    try:
        return resolve_runtime_template(name, cli, env=os.environ)
    except ValueError as exc:
        _raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_runtime_template",
            str(exc),
        )


def _spawn_request(
    body: CreateRunRequest,
    settings: Settings,
    *,
    launch_fields: dict[str, object] | None = None,
    runtime_template: RuntimeTemplateRef | None = None,
) -> SpawnRun:
    terminal = body.terminal or TerminalSizeModel()
    return SpawnRun(
        cli=_validated_cli(body.cli),
        cwd=_request_cwd(body.cwd, settings),
        cols=terminal.cols,
        rows=terminal.rows,
        passthrough=settings.default_client_passthrough,
        home_dir=settings.agent_home_dir,
        debug=settings.debug,
        osc_color_replies=body.osc_color_replies,
        runtime_template=runtime_template,
        launch_fields=launch_fields or {},
        idempotency_key=body.idempotency_key,
    )


def _workspace_id_for_view(view: ManagedRunView) -> str:
    wid = workspace_id(view.cwd)
    return f"{wid.slug}/{wid.hash}"


def _session_id_for_view(view: ManagedRunView) -> str:
    if view.native_session_id is None:
        return view.run_id
    if view.cli == CODEX_CLIENT_NAME:
        return synth_session_id(view.run_id, "codex", view.native_session_id)
    return view.native_session_id


def _curated_state(state: RunState) -> PublicRunState:
    if state is RunState.STARTING:
        return "RUNNING"
    return cast("PublicRunState", state.value)


def run_view_model(view: ManagedRunView) -> RunViewModel:
    end_reason = view.end_reason if view.end_reason in _END_REASONS else None
    return RunViewModel(
        run_id=view.run_id,
        workspace_id=_workspace_id_for_view(view),
        session_id=_session_id_for_view(view),
        cli=view.cli,
        state=_curated_state(view.state),
        end_reason=cast(
            'Literal["explicit", "idle-timeout", "shutdown", "deploy-restart"] | None',
            end_reason,
        ),
        error=view.error,
        created_at=view.created_at.isoformat(),
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
    owner: str = Query(default=DEFAULT_OWNER, min_length=1),
    _origin: None = Depends(require_http_origin),
) -> dict[str, object]:
    manager = _run_manager(request)
    try:
        cli = _validated_cli(body.cli)
        runtime_template = _runtime_template_ref(body, cli)
        spawn_request = _spawn_request(
            body,
            get_settings(),
            runtime_template=runtime_template,
        )
        launch_fields = await _launch_fields(body, request=request, owner=owner)
        if launch_fields:
            spawn_request = replace(spawn_request, launch_fields=launch_fields)
        run = await manager.spawn(spawn_request)
    except RunManagerError as exc:
        _http_error_from_manager(exc)
    return _response_payload(CreateRunResponse(run=run_view_model(run.view())))


@router.get(RUNS_ROUTE_PREFIX)
async def list_runs(
    request: Request,
    state: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_RUNS_LIMIT, ge=1, le=MAX_RUNS_LIMIT),
    cursor: str | None = Query(default=None),
) -> dict[str, object]:
    cursor_filters = _cursor_filter_key(state)
    offset = _decode_cursor(cursor, filters=cursor_filters) if cursor is not None else 0
    filters = RunFilters(
        states=frozenset({_validated_state(state)}) if state is not None else None,
    )
    manager = _run_manager(request)
    views = manager.list(filters)
    page = views[offset : offset + limit]
    next_offset = offset + limit
    next_cursor = (
        _encode_cursor(next_offset, filters=cursor_filters) if next_offset < len(views) else None
    )
    return {"items": [run_view_payload(view) for view in page], "nextCursor": next_cursor}


@router.get(RUNS_ROUTE_PREFIX + "/{run_id}")
async def get_run(run_id: str, request: Request) -> dict[str, object]:
    manager = _run_manager(request)
    try:
        view = manager.get(run_id).view()
    except RunNotFoundError:
        _not_found(run_id)
    return _response_payload(CreateRunResponse(run=run_view_model(view)))


@router.post(RUNS_ROUTE_PREFIX + "/{run_id}/terminate")
async def terminate_run(
    run_id: str,
    request: Request,
    _origin: None = Depends(require_http_origin),
) -> dict[str, object]:
    manager = _run_manager(request)
    try:
        view = await manager.terminate(run_id, reason="explicit")
    except RunNotFoundError:
        _not_found(run_id)
    return _response_payload(TerminateRunResponse(run=run_view_model(view)))


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
        await send_run_error_and_close(websocket, code=exc.code, message=exc.message)
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
