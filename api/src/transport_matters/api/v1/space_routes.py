"""Space, Worktree, and Canvas API routes."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field

from transport_matters.api.v1.errors import raise_api_error
from transport_matters.api.v1.run_routes import require_http_origin
from transport_matters.api.v1.session_store import optional_session_pool
from transport_matters.space.detection import SpaceDetectionError
from transport_matters.space.models import Canvas, CanvasId, SpaceId, Worktree, WorktreeId
from transport_matters.space.store import SpaceSnapshot, SpaceStore

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from psycopg.rows import DictRow
    from psycopg_pool import AsyncConnectionPool

router = APIRouter()
DEFAULT_OWNER = "local"
DEFAULT_SPACES_LIMIT = 50
MAX_SPACES_LIMIT = 100
SpaceKind = Literal["repo", "plain"]


class WorktreeSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    worktree_id: str = Field(serialization_alias="worktreeId")
    space_id: str = Field(serialization_alias="spaceId")
    path: str | None = None
    workspace_slug: str = Field(serialization_alias="workspaceSlug")
    workspace_hash: str = Field(serialization_alias="workspaceHash")
    branch: str | None = None
    head_oid: str | None = Field(default=None, serialization_alias="headOid")
    is_primary: bool = Field(serialization_alias="isPrimary")
    missing: bool
    archived: bool


class SpaceSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    space_id: str = Field(serialization_alias="spaceId")
    label: str
    kind: SpaceKind
    archived: bool
    created_at: datetime | None = Field(default=None, serialization_alias="createdAt")
    updated_at: datetime | None = Field(default=None, serialization_alias="updatedAt")
    worktrees: list[WorktreeSummary]


class CanvasSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    canvas_id: str = Field(serialization_alias="canvasId")
    space_id: str = Field(serialization_alias="spaceId")
    label: str
    default_worktree_id: str | None = Field(default=None, serialization_alias="defaultWorktreeId")
    layout: dict[str, Any] = Field(default_factory=dict)
    layout_version: int = Field(serialization_alias="layoutVersion")
    archived: bool


class ListSpacesResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[SpaceSummary]
    next_cursor: str | None = Field(default=None, serialization_alias="nextCursor")


class WorktreeListResponse(BaseModel):
    items: list[WorktreeSummary]


class CanvasListResponse(BaseModel):
    items: list[CanvasSummary]


class SpaceDetailResponse(BaseModel):
    space: SpaceSummary
    worktrees: list[WorktreeSummary]
    canvases: list[CanvasSummary]


class ResolveSpaceRequest(BaseModel):
    cwd: str
    create: bool = True


class ResolveSpaceResponse(BaseModel):
    space: SpaceSummary
    worktree: WorktreeSummary
    canvases: list[CanvasSummary]


class PatchSpaceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    label: str | None = None
    archived: bool | None = None


class SpaceMutationResponse(BaseModel):
    space: SpaceSummary


class CreateCanvasRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    label: str
    default_worktree_id: str | None = Field(default=None, validation_alias="defaultWorktreeId")
    layout: dict[str, Any] = Field(default_factory=dict)


class PatchCanvasRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    label: str | None = None
    default_worktree_id: str | None = Field(default=None, validation_alias="defaultWorktreeId")
    layout: dict[str, Any] | None = None
    archived: bool | None = None


class CanvasMutationResponse(BaseModel):
    canvas: CanvasSummary


def _response_payload(response: BaseModel) -> dict[str, object]:
    return response.model_dump(mode="json", by_alias=True, exclude_none=True)


async def _session_pool(request: Request) -> AsyncConnectionPool[AsyncConnection[DictRow]]:
    pool = optional_session_pool(request)
    if pool is None:
        raise_api_error(
            http_status.HTTP_503_SERVICE_UNAVAILABLE,
            "session_store_unavailable",
            "session store unavailable",
        )
    return pool


def _encode_cursor(offset: int) -> str:
    payload = json.dumps({"offset": offset}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> int:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
    except binascii.Error, json.JSONDecodeError, UnicodeDecodeError:
        raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    if not isinstance(payload, dict):
        raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    offset = payload.get("offset")
    if not isinstance(offset, int) or offset < 0:
        raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    return offset


def _parse_space_id(value: str) -> SpaceId:
    try:
        return SpaceId.parse(value)
    except ValueError:
        return raise_api_error(
            http_status.HTTP_400_BAD_REQUEST, "invalid_space_id", "space id must be a UUID"
        )


def _parse_worktree_id(value: str | None) -> WorktreeId | None:
    if value is None:
        return None
    try:
        return WorktreeId.parse(value)
    except ValueError:
        return raise_api_error(
            http_status.HTTP_400_BAD_REQUEST, "invalid_worktree_id", "worktree id must be a UUID"
        )


def _parse_canvas_id(value: str) -> CanvasId:
    try:
        return CanvasId.parse(value)
    except ValueError:
        return raise_api_error(
            http_status.HTTP_400_BAD_REQUEST, "invalid_canvas_id", "canvas id must be a UUID"
        )


def _request_cwd(cwd: str) -> Path:
    path = Path(cwd).expanduser()
    if not path.is_absolute():
        raise_api_error(http_status.HTTP_400_BAD_REQUEST, "invalid_cwd", "cwd must be absolute")
    return path


def _space_summary(snapshot: SpaceSnapshot) -> SpaceSummary:
    return SpaceSummary(
        space_id=str(snapshot.space.space_id),
        label=snapshot.space.name,
        kind="repo" if snapshot.git_identity is not None else "plain",
        archived=snapshot.space.archived,
        created_at=snapshot.space.created_at,
        updated_at=snapshot.space.updated_at,
        worktrees=[_worktree_summary(item) for item in snapshot.worktrees],
    )


def _worktree_summary(worktree: Worktree) -> WorktreeSummary:
    return WorktreeSummary(
        worktree_id=str(worktree.worktree_id),
        space_id=str(worktree.space_id),
        path=worktree.path,
        workspace_slug=worktree.workspace_slug,
        workspace_hash=worktree.workspace_hash,
        branch=worktree.branch_name,
        head_oid=worktree.head_oid,
        is_primary=worktree.is_primary,
        missing=worktree.missing,
        archived=worktree.archived,
    )


def _canvas_summary(canvas: Canvas) -> CanvasSummary:
    return CanvasSummary(
        canvas_id=str(canvas.canvas_id),
        space_id=str(canvas.space_id),
        label=canvas.name,
        default_worktree_id=str(canvas.default_worktree_id) if canvas.default_worktree_id else None,
        layout=canvas.layout,
        layout_version=canvas.layout_version,
        archived=canvas.archived,
    )


def _detail_response(snapshot: SpaceSnapshot) -> SpaceDetailResponse:
    return SpaceDetailResponse(
        space=_space_summary(snapshot),
        worktrees=[_worktree_summary(item) for item in snapshot.worktrees],
        canvases=[_canvas_summary(item) for item in snapshot.canvases],
    )


def _worktree_for_cwd(snapshot: SpaceSnapshot, cwd: Path) -> Worktree | None:
    resolved = str(cwd.resolve(strict=False))
    for worktree in snapshot.worktrees:
        if worktree.path == resolved:
            return worktree
    return None


def _refresh_path(snapshot: SpaceSnapshot) -> Path:
    for worktree in snapshot.worktrees:
        if worktree.path is not None and not worktree.missing and not worktree.archived:
            return Path(worktree.path)
    return raise_api_error(
        http_status.HTTP_409_CONFLICT,
        "space_not_refreshable",
        "space has no active worktree path to refresh from",
    )


def _require_worktree_in_space(snapshot: SpaceSnapshot, worktree_id: WorktreeId | None) -> None:
    if worktree_id is None:
        return
    if any(item.worktree_id == worktree_id for item in snapshot.worktrees):
        return
    raise_api_error(
        http_status.HTTP_400_BAD_REQUEST,
        "invalid_worktree_id",
        "defaultWorktreeId must belong to the target space",
    )


async def _require_snapshot(store: SpaceStore, space_id: SpaceId, *, owner: str) -> SpaceSnapshot:
    snapshot = await store.get_space_snapshot(space_id, owner=owner)
    if snapshot is None:
        raise_api_error(http_status.HTTP_404_NOT_FOUND, "space_not_found", "space not found")
    return snapshot


async def _require_canvas_space_id(
    conn: AsyncConnection[DictRow], canvas_id: CanvasId, *, owner: str
) -> SpaceId:
    cursor = await conn.execute(
        """
        SELECT space_id
        FROM canvas
        WHERE canvas_id = %(canvas_id)s AND owner = %(owner)s
        """,
        {"canvas_id": canvas_id.into_uuid(), "owner": owner},
    )
    row = await cursor.fetchone()
    if row is None:
        raise_api_error(http_status.HTTP_404_NOT_FOUND, "canvas_not_found", "canvas not found")
    return SpaceId.from_uuid(row["space_id"])


@router.get("/spaces")
async def list_spaces(
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    limit: Annotated[int, Query(ge=1, le=MAX_SPACES_LIMIT)] = DEFAULT_SPACES_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    offset = _decode_cursor(cursor) if cursor is not None else 0
    async with pool.connection() as conn:
        summaries = await SpaceStore(conn).list_spaces(owner=owner, limit=limit + 1, offset=offset)
    snapshots = [
        SpaceSnapshot(item.space, item.git_identity, item.worktrees) for item in summaries[:limit]
    ]
    next_cursor = _encode_cursor(offset + limit) if len(summaries) > limit else None
    return _response_payload(
        ListSpacesResponse(
            items=[_space_summary(item) for item in snapshots], next_cursor=next_cursor
        )
    )


@router.post("/spaces/resolve")
async def resolve_space(
    body: ResolveSpaceRequest,
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    _origin: None = Depends(require_http_origin),
) -> dict[str, object]:
    cwd = _request_cwd(body.cwd)
    try:
        async with pool.connection() as conn:
            snapshot = await SpaceStore(conn).resolve_cwd(cwd, owner=owner, create=body.create)
    except SpaceDetectionError as exc:
        raise_api_error(http_status.HTTP_400_BAD_REQUEST, exc.code, exc.message, exc.details)
    if snapshot is None:
        raise_api_error(http_status.HTTP_404_NOT_FOUND, "space_not_found", "space not found")
    worktree = _worktree_for_cwd(snapshot, cwd)
    if worktree is None:
        raise_api_error(
            http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            "worktree_resolution_failed",
            "resolved space did not include the requested cwd",
        )
    return _response_payload(
        ResolveSpaceResponse(
            space=_space_summary(snapshot),
            worktree=_worktree_summary(worktree),
            canvases=[_canvas_summary(item) for item in snapshot.canvases],
        )
    )


@router.get("/spaces/{space_id}")
async def get_space(
    space_id: str,
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
) -> dict[str, object]:
    parsed = _parse_space_id(space_id)
    async with pool.connection() as conn:
        snapshot = await _require_snapshot(SpaceStore(conn), parsed, owner=owner)
    return _response_payload(_detail_response(snapshot))


@router.patch("/spaces/{space_id}")
async def patch_space(
    space_id: str,
    body: PatchSpaceRequest,
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    _origin: None = Depends(require_http_origin),
) -> dict[str, object]:
    parsed = _parse_space_id(space_id)
    async with pool.connection() as conn:
        store = SpaceStore(conn)
        updated = await store.update_space(
            parsed, owner=owner, name=body.label, archived=body.archived
        )
        if updated is None:
            raise_api_error(http_status.HTTP_404_NOT_FOUND, "space_not_found", "space not found")
        snapshot = await _require_snapshot(store, parsed, owner=owner)
    return _response_payload(SpaceMutationResponse(space=_space_summary(snapshot)))


@router.get("/spaces/{space_id}/worktrees")
async def list_space_worktrees(
    space_id: str,
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    refresh: Annotated[bool, Query()] = False,
) -> dict[str, object]:
    parsed = _parse_space_id(space_id)
    try:
        async with pool.connection() as conn:
            store = SpaceStore(conn)
            snapshot = await _require_snapshot(store, parsed, owner=owner)
            if refresh:
                refreshed = await store.resolve_cwd(
                    _refresh_path(snapshot), owner=owner, create=True
                )
                if refreshed is None:
                    raise_api_error(
                        http_status.HTTP_404_NOT_FOUND, "space_not_found", "space not found"
                    )
                snapshot = refreshed
    except SpaceDetectionError as exc:
        raise_api_error(http_status.HTTP_400_BAD_REQUEST, exc.code, exc.message, exc.details)
    return _response_payload(
        WorktreeListResponse(items=[_worktree_summary(item) for item in snapshot.worktrees])
    )


@router.get("/spaces/{space_id}/canvases")
async def list_space_canvases(
    space_id: str,
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
) -> dict[str, object]:
    parsed = _parse_space_id(space_id)
    async with pool.connection() as conn:
        snapshot = await _require_snapshot(SpaceStore(conn), parsed, owner=owner)
    return _response_payload(
        CanvasListResponse(items=[_canvas_summary(item) for item in snapshot.canvases])
    )


@router.post("/spaces/{space_id}/canvases", status_code=http_status.HTTP_201_CREATED)
async def create_canvas(
    space_id: str,
    body: CreateCanvasRequest,
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    _origin: None = Depends(require_http_origin),
) -> dict[str, object]:
    parsed = _parse_space_id(space_id)
    default_worktree_id = _parse_worktree_id(body.default_worktree_id)
    async with pool.connection() as conn:
        store = SpaceStore(conn)
        snapshot = await _require_snapshot(store, parsed, owner=owner)
        _require_worktree_in_space(snapshot, default_worktree_id)
        canvas = await store.create_canvas(
            parsed,
            owner=owner,
            name=body.label,
            default_worktree_id=default_worktree_id,
            layout=body.layout,
        )
    return _response_payload(CanvasMutationResponse(canvas=_canvas_summary(canvas)))


@router.patch("/canvases/{canvas_id}")
async def patch_canvas(
    canvas_id: str,
    body: PatchCanvasRequest,
    pool: Any = Depends(_session_pool),
    owner: Annotated[str, Query(min_length=1)] = DEFAULT_OWNER,
    _origin: None = Depends(require_http_origin),
) -> dict[str, object]:
    parsed = _parse_canvas_id(canvas_id)
    default_worktree_id = _parse_worktree_id(body.default_worktree_id)
    async with pool.connection() as conn:
        store = SpaceStore(conn)
        canvas_space_id = await _require_canvas_space_id(conn, parsed, owner=owner)
        snapshot = await _require_snapshot(store, canvas_space_id, owner=owner)
        _require_worktree_in_space(snapshot, default_worktree_id)
        canvas = await store.update_canvas(
            parsed,
            owner=owner,
            name=body.label,
            default_worktree_id=default_worktree_id,
            layout=body.layout,
            archived=body.archived,
        )
    if canvas is None:
        raise_api_error(http_status.HTTP_404_NOT_FOUND, "canvas_not_found", "canvas not found")
    return _response_payload(CanvasMutationResponse(canvas=_canvas_summary(canvas)))
