"""Managed captured run API routes."""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import TYPE_CHECKING, Any, Literal, NoReturn, cast

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketException
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field
from starlette.websockets import WebSocketDisconnect

from transport_matters.api.v1 import terminal_bridge
from transport_matters.api.v1.errors import raise_api_error
from transport_matters.api.v1.responses import (
    decode_cursor,
    encode_cursor,
    raise_not_found,
    response_payload,
)
from transport_matters.api.v1.run_continuation import (
    ContinuationSessionNotFound,
    build_continuation_launch_fields,
)
from transport_matters.api.v1.session_store import optional_session_pool
from transport_matters.captured_run import CLAUDE_HARNESS_NAME, CODEX_HARNESS_NAME
from transport_matters.captured_run_models import CapturedRunHarness
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
from transport_matters.space.models import ResolvedWorktree, SpaceId, WorktreeId
from transport_matters.space.store import SpaceStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from transport_matters.runtime_templates import RuntimeTemplateRef

RUNS_ROUTE_PREFIX = "/runs"
DEFAULT_RUNS_LIMIT = 50
MAX_RUNS_LIMIT = 100
DEFAULT_OWNER = "local"
_CAPTURED_RUN_HARNESS_ALLOWLIST = frozenset({CLAUDE_HARNESS_NAME, CODEX_HARNESS_NAME})
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
    "unsupported_harness": http_status.HTTP_400_BAD_REQUEST,
}
_CURATED_STATES = frozenset(
    {RunState.RUNNING, RunState.TERMINATING, RunState.TERMINATED, RunState.EXITED, RunState.FAILED}
)
_END_REASONS = frozenset({"explicit", "idle-timeout", "shutdown", "deploy-restart"})
PublicRunState = Literal["RUNNING", "TERMINATING", "TERMINATED", "EXITED", "FAILED"]
# Single source of truth for internal states presented under a different public label.
# STARTING is the pre-attach phase of a run and surfaces to clients as RUNNING; the
# curated view and the list-filter expansion both derive from this mapping.
_PUBLIC_STATE_ALIASES: dict[RunState, PublicRunState] = {RunState.STARTING: "RUNNING"}

router = APIRouter()


class TerminalSizeModel(BaseModel):
    cols: int = Field(default=terminal_bridge.DEFAULT_COLS, ge=1, le=terminal_bridge.MAX_COLS)
    rows: int = Field(default=terminal_bridge.DEFAULT_ROWS, ge=1, le=terminal_bridge.MAX_ROWS)


class CreateRunRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    harness: str
    worktree_id: str | None = Field(default=None, alias="worktreeId")
    terminal: TerminalSizeModel | None = None
    # Bridge answers the harness OSC 10/11 color queries (see osc_color_responder).
    osc_color_replies: bool = Field(default=True, alias="oscColorReplies")
    continue_from_session_id: str | None = Field(default=None, alias="continueFromSessionId")
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey")
    runtime_template: str | None = Field(default=None, alias="runtimeTemplate")
    bypass_permissions: bool = Field(default=False, alias="bypassPermissions")


class RunViewModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(serialization_alias="runId")
    space_id: str = Field(serialization_alias="spaceId")
    worktree_id: str = Field(serialization_alias="worktreeId")
    session_id: str = Field(serialization_alias="sessionId")
    harness: CapturedRunHarness
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


def create_run_manager(
    shared_proxy_manager: Any | None = None,
    shared_proxy_unavailable_reason: str | None = None,
) -> RunManager:
    settings = get_settings()
    return RunManager(
        spawn_concurrency=settings.captured_run_spawn_concurrency,
        shared_proxy_manager=shared_proxy_manager,
        shared_proxy_unavailable_reason=shared_proxy_unavailable_reason,
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


def _http_error_from_manager(exc: RunManagerError) -> NoReturn:
    status_code = _RUN_MANAGER_HTTP_STATUS.get(exc.code)
    if status_code is None:
        raise_api_error(
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            "unmapped_run_manager_error",
            "unmapped run manager error",
            {"code": exc.code},
        )
    raise_api_error(status_code, exc.code, exc.message)


async def require_http_origin(request: Request) -> None:
    if terminal_bridge.origin_allowed_for_request(request, get_settings()):
        return
    raise_api_error(http_status.HTTP_403_FORBIDDEN, "origin_not_allowed", "origin not allowed")


def _validated_harness(harness: str) -> CapturedRunHarness:
    if harness not in _CAPTURED_RUN_HARNESS_ALLOWLIST:
        raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "unsupported_harness",
            f"unsupported captured run harness: {harness}",
        )
    return cast("CapturedRunHarness", harness)


def _validated_state(state: str) -> RunState:
    try:
        parsed = RunState(state)
    except ValueError:
        raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_request",
            f"unsupported run state: {state}",
        )
    if parsed not in _CURATED_STATES:
        raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_request",
            f"unsupported run state: {state}",
        )
    return parsed


def _public_state_filter(state: str) -> frozenset[RunState]:
    parsed = _validated_state(state)
    aliased = frozenset(
        internal for internal, public in _PUBLIC_STATE_ALIASES.items() if public == parsed.value
    )
    return frozenset({parsed, *aliased})


def _cursor_filter_key(
    state: str | None, space_id: str | None, worktree_id: str | None
) -> dict[str, str | None]:
    return {"state": state, "spaceId": space_id, "worktreeId": worktree_id}


def _parse_uuid_id[IdT: (SpaceId, WorktreeId)](
    value: str | None,
    id_type: type[IdT],
    field_name: str,
    invalid_code: str,
    required_code: str | None = None,
) -> IdT | None:
    if value is None or value == "":
        if required_code is None:
            return None
        raise_api_error(
            http_status.HTTP_400_BAD_REQUEST, required_code, f"{field_name} is required"
        )
    try:
        return id_type.parse(value)
    except ValueError:
        return raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            invalid_code,
            f"{field_name} must be a UUID",
        )


async def _resolved_worktree(
    body: CreateRunRequest, *, request: Request, owner: str
) -> ResolvedWorktree:
    worktree_id = _parse_uuid_id(
        body.worktree_id, WorktreeId, "worktreeId", "invalid_worktree_id", "worktree_required"
    )
    assert worktree_id is not None
    pool = optional_session_pool(request)
    if pool is None:
        raise_api_error(
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
            "session_store_unavailable",
            "session store unavailable",
        )
    async with pool.connection() as conn:
        resolved = await SpaceStore(conn).resolve_worktree(worktree_id, owner=owner)
    if resolved is None:
        raise_api_error(http_status.HTTP_404_NOT_FOUND, "worktree_not_found", "worktree not found")
    if resolved.missing or resolved.archived:
        raise_api_error(
            http_status.HTTP_409_CONFLICT,
            "worktree_unavailable",
            "worktree is missing or archived",
        )
    return resolved


def _required_non_empty(value: str | None, *, field_name: str) -> str:
    if value is None or value.strip() == "":
        raise_api_error(
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
        raise_api_error(
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
            "session_store_unavailable",
            "session store unavailable",
        )
    try:
        continuation = await build_continuation_launch_fields(
            pool, parent_session_id=parent_session_id, owner=owner
        )
    except ContinuationSessionNotFound:
        raise_not_found("session_not_found", f"session {parent_session_id!r} was not found")
    return continuation.fields


def _runtime_template_ref(
    body: CreateRunRequest, harness: CapturedRunHarness
) -> RuntimeTemplateRef | None:
    name = body.runtime_template
    if name is None or name.strip() == "":
        return None
    try:
        return resolve_runtime_template(name, harness, env=os.environ)
    except ValueError as exc:
        return raise_api_error(
            http_status.HTTP_400_BAD_REQUEST,
            "invalid_runtime_template",
            str(exc),
        )


def _spawn_request(
    body: CreateRunRequest,
    settings: Settings,
    *,
    resolved_worktree: ResolvedWorktree,
    launch_fields: dict[str, object] | None = None,
    runtime_template: RuntimeTemplateRef | None = None,
) -> SpawnRun:
    terminal = body.terminal or TerminalSizeModel()
    harness = _validated_harness(body.harness)
    return SpawnRun(
        harness=harness,
        resolved_worktree=resolved_worktree,
        cols=terminal.cols,
        rows=terminal.rows,
        passthrough=(),
        home_dir=settings.agent_home_dir,
        debug=settings.debug,
        osc_color_replies=body.osc_color_replies,
        runtime_template=runtime_template,
        launch_fields=launch_fields or {},
        idempotency_key=body.idempotency_key,
        start_on_attach=True,
        defer_session_ownership=harness == CODEX_HARNESS_NAME,
        bypass_permissions=body.bypass_permissions,
    )


def _session_id_for_view(view: ManagedRunView) -> str:
    if view.native_session_id is None:
        return view.run_id
    if view.harness == CODEX_HARNESS_NAME:
        return synth_session_id(view.run_id, "codex", view.native_session_id)
    return view.native_session_id


def _curated_state(state: RunState) -> PublicRunState:
    alias = _PUBLIC_STATE_ALIASES.get(state)
    if alias is not None:
        return alias
    return cast("PublicRunState", state.value)


def run_view_model(view: ManagedRunView) -> RunViewModel:
    end_reason = view.end_reason if view.end_reason in _END_REASONS else None
    return RunViewModel(
        run_id=view.run_id,
        space_id=str(view.space_id),
        worktree_id=str(view.worktree_id),
        session_id=_session_id_for_view(view),
        harness=view.harness,
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


@router.post(RUNS_ROUTE_PREFIX, status_code=http_status.HTTP_201_CREATED)
async def create_run(
    body: CreateRunRequest,
    request: Request,
    owner: str = Query(default=DEFAULT_OWNER, min_length=1),
    _origin: None = Depends(require_http_origin),
) -> dict[str, object]:
    manager = _run_manager(request)
    try:
        harness = _validated_harness(body.harness)
        runtime_template = _runtime_template_ref(body, harness)
        resolved = await _resolved_worktree(body, request=request, owner=owner)
        launch_fields = await _launch_fields(body, request=request, owner=owner)
        spawn_request = _spawn_request(
            body,
            get_settings(),
            resolved_worktree=resolved,
            launch_fields=launch_fields,
            runtime_template=runtime_template,
        )
        run = await manager.spawn(spawn_request)
    except RunManagerError as exc:
        _http_error_from_manager(exc)
    return response_payload(CreateRunResponse(run=run_view_model(run.view())))


@router.get(RUNS_ROUTE_PREFIX)
async def list_runs(
    request: Request,
    state: str | None = Query(default=None),
    space_id: str | None = Query(default=None, alias="spaceId"),
    worktree_id: str | None = Query(default=None, alias="worktreeId"),
    limit: int = Query(default=DEFAULT_RUNS_LIMIT, ge=1, le=MAX_RUNS_LIMIT),
    cursor: str | None = Query(default=None),
) -> dict[str, object]:
    cursor_filters = _cursor_filter_key(state, space_id, worktree_id)
    offset = decode_cursor(cursor, filters=cursor_filters) if cursor is not None else 0
    filters = RunFilters(
        space_id=_parse_uuid_id(space_id, SpaceId, "spaceId", "invalid_space_id"),
        worktree_id=_parse_uuid_id(worktree_id, WorktreeId, "worktreeId", "invalid_worktree_id"),
        states=_public_state_filter(state) if state is not None else None,
    )
    manager = _run_manager(request)
    views = manager.list(filters)
    page = views[offset : offset + limit]
    next_offset = offset + limit
    next_cursor = (
        encode_cursor(next_offset, filters=cursor_filters) if next_offset < len(views) else None
    )
    return {"items": [run_view_payload(view) for view in page], "nextCursor": next_cursor}


@router.get(RUNS_ROUTE_PREFIX + "/{run_id}")
async def get_run(run_id: str, request: Request) -> dict[str, object]:
    manager = _run_manager(request)
    try:
        view = manager.get(run_id).view()
    except RunNotFoundError:
        raise_not_found("run_not_found", f"run not found: {run_id}")
    return response_payload(CreateRunResponse(run=run_view_model(view)))


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
        raise_not_found("run_not_found", f"run not found: {run_id}")
    return response_payload(TerminateRunResponse(run=run_view_model(view)))


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
    attached = await manager.attach(run_id, cols=cols, rows=rows)
    attachment_id = attached.attachment.attachment_id
    run = manager.get(run_id)
    terminal = run.terminal
    if terminal is None:
        raise RunManagerError("run_not_attachable", f"run {run_id} has not started")
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
                terminal.master_fd,
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
