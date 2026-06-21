from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from transport_matters.config import get_settings
from transport_matters.space.detection import DetectedSpace, DetectedWorktree, detect_space
from transport_matters.space.models import (
    Canvas,
    CanvasId,
    ResolvedWorktree,
    Space,
    SpaceGitIdentity,
    SpaceId,
    Worktree,
    WorktreeId,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from psycopg import AsyncConnection
    from psycopg.rows import DictRow


@dataclass(frozen=True)
class SpaceSummary:
    space: Space
    git_identity: SpaceGitIdentity | None
    worktrees: tuple[Worktree, ...]


@dataclass(frozen=True)
class SpaceSnapshot:
    space: Space
    git_identity: SpaceGitIdentity | None
    worktrees: tuple[Worktree, ...]
    canvases: tuple[Canvas, ...] = ()


class SpaceStore:
    def __init__(self, conn: AsyncConnection[DictRow], *, storage_dir: Path | None = None) -> None:
        self._conn = conn
        self._storage_dir = storage_dir or get_settings().storage_dir

    async def resolve_cwd(
        self,
        cwd: Path | str,
        *,
        owner: str = "local",
        create: bool = True,
    ) -> SpaceSnapshot | None:
        detection = detect_space(Path(cwd))
        if create:
            return await self.upsert_detection(detection, owner=owner)
        return await self._find_detection(detection, owner=owner)

    async def upsert_detection(
        self,
        detection: DetectedSpace,
        *,
        owner: str = "local",
    ) -> SpaceSnapshot:
        async with self._conn.transaction():
            if detection.repo_instance_key is not None and detection.git_common_dir is not None:
                space = await self._claim_git_space(detection, owner=owner)
            else:
                existing_space = await self._lookup_space_for_detection(detection, owner=owner)
                space = existing_space or await self._insert_space(owner=owner, name=detection.name)

            seen_paths: list[str] = []
            for detected in detection.worktrees:
                seen_paths.append(str(detected.path))
                await self._upsert_worktree(space.space_id, detected, owner=owner)
            if detection.repo_instance_key is not None:
                await self._mark_missing_worktrees(
                    space.space_id,
                    owner=owner,
                    active_paths=seen_paths,
                )

            snapshot = await self.get_space_snapshot(space.space_id, owner=owner)
            if snapshot is None:
                raise RuntimeError("space disappeared after upsert")
        self._write_cache(snapshot)
        return snapshot

    async def list_spaces(
        self,
        *,
        owner: str = "local",
        limit: int = 50,
        offset: int = 0,
    ) -> list[SpaceSummary]:
        cursor = await self._conn.execute(
            """
            SELECT s.space_id, s.owner, s.name, s.archived, s.created_at, s.updated_at,
                   gi.repo_instance_key, gi.git_common_dir, gi.detected_at
            FROM space AS s
            LEFT JOIN space_git_identity AS gi ON gi.space_id = s.space_id
            WHERE s.owner = %(owner)s
            ORDER BY s.updated_at DESC, s.name, s.space_id
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"owner": owner, "limit": limit, "offset": offset},
        )
        rows = await cursor.fetchall()
        summaries: list[SpaceSummary] = []
        for row in rows:
            space = _space_from_row(row)
            worktrees = tuple(await self.list_worktrees(space.space_id, owner=owner))
            summaries.append(SpaceSummary(space, _identity_from_row(row), worktrees))
        return summaries

    async def get_space_snapshot(
        self,
        space_id: SpaceId,
        *,
        owner: str = "local",
    ) -> SpaceSnapshot | None:
        cursor = await self._conn.execute(
            """
            SELECT s.space_id, s.owner, s.name, s.archived, s.created_at, s.updated_at,
                   gi.repo_instance_key, gi.git_common_dir, gi.detected_at
            FROM space AS s
            LEFT JOIN space_git_identity AS gi ON gi.space_id = s.space_id
            WHERE s.space_id = %(space_id)s AND s.owner = %(owner)s
            """,
            {"space_id": space_id.into_uuid(), "owner": owner},
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return SpaceSnapshot(
            space=_space_from_row(row),
            git_identity=_identity_from_row(row),
            worktrees=tuple(await self.list_worktrees(space_id, owner=owner)),
            canvases=tuple(await self.list_canvases(space_id, owner=owner)),
        )

    async def update_space(
        self,
        space_id: SpaceId,
        *,
        owner: str = "local",
        name: str | None = None,
        archived: bool | None = None,
    ) -> Space | None:
        cursor = await self._conn.execute(
            """
            UPDATE space
            SET name = COALESCE(%(name)s, name),
                archived = COALESCE(%(archived)s, archived),
                updated_at = now()
            WHERE space_id = %(space_id)s AND owner = %(owner)s
            RETURNING space_id, owner, name, archived, created_at, updated_at
            """,
            {"space_id": space_id.into_uuid(), "owner": owner, "name": name, "archived": archived},
        )
        row = await cursor.fetchone()
        return _space_from_row(row) if row is not None else None

    async def list_worktrees(self, space_id: SpaceId, *, owner: str = "local") -> list[Worktree]:
        cursor = await self._conn.execute(
            """
            SELECT worktree_id, space_id, owner, path, workspace_slug, workspace_hash,
                   branch_name, head_oid, is_primary, missing, archived,
                   detected_at, created_at, updated_at
            FROM space_worktree
            WHERE space_id = %(space_id)s AND owner = %(owner)s
            ORDER BY is_primary DESC, missing, path NULLS LAST, workspace_slug, workspace_hash
            """,
            {"space_id": space_id.into_uuid(), "owner": owner},
        )
        rows = await cursor.fetchall()
        return [_worktree_from_row(row) for row in rows]

    async def get_worktree(
        self,
        worktree_id: WorktreeId,
        *,
        owner: str = "local",
    ) -> Worktree | None:
        cursor = await self._conn.execute(
            """
            SELECT worktree_id, space_id, owner, path, workspace_slug, workspace_hash,
                   branch_name, head_oid, is_primary, missing, archived,
                   detected_at, created_at, updated_at
            FROM space_worktree
            WHERE worktree_id = %(worktree_id)s AND owner = %(owner)s
            """,
            {"worktree_id": worktree_id.into_uuid(), "owner": owner},
        )
        row = await cursor.fetchone()
        return _worktree_from_row(row) if row is not None else None

    async def resolve_worktree(
        self,
        worktree_id: WorktreeId,
        *,
        owner: str = "local",
    ) -> ResolvedWorktree | None:
        worktree = await self.get_worktree(worktree_id, owner=owner)
        if worktree is None or worktree.path is None:
            return None
        return ResolvedWorktree(
            space_id=worktree.space_id,
            worktree_id=worktree.worktree_id,
            cwd=worktree.path,
            workspace_slug=worktree.workspace_slug,
            workspace_hash=worktree.workspace_hash,
            missing=worktree.missing,
            archived=worktree.archived,
        )

    async def list_canvases(self, space_id: SpaceId, *, owner: str = "local") -> list[Canvas]:
        cursor = await self._conn.execute(
            """
            SELECT canvas_id, space_id, owner, name, default_worktree_id, layout,
                   layout_version, archived, created_at, updated_at
            FROM canvas
            WHERE space_id = %(space_id)s AND owner = %(owner)s
            ORDER BY updated_at DESC, name, canvas_id
            """,
            {"space_id": space_id.into_uuid(), "owner": owner},
        )
        rows = await cursor.fetchall()
        return [_canvas_from_row(row) for row in rows]

    async def create_canvas(
        self,
        space_id: SpaceId,
        *,
        owner: str = "local",
        name: str,
        default_worktree_id: WorktreeId | None = None,
        layout: dict[str, Any] | None = None,
    ) -> Canvas:
        canvas_id = CanvasId.new()
        cursor = await self._conn.execute(
            """
            INSERT INTO canvas (canvas_id, space_id, owner, name, default_worktree_id, layout)
            VALUES (%(canvas_id)s, %(space_id)s, %(owner)s, %(name)s,
                    %(default_worktree_id)s, %(layout)s::jsonb)
            RETURNING canvas_id, space_id, owner, name, default_worktree_id, layout,
                      layout_version, archived, created_at, updated_at
            """,
            {
                "canvas_id": canvas_id.into_uuid(),
                "space_id": space_id.into_uuid(),
                "owner": owner,
                "name": name,
                "default_worktree_id": _uuid_or_none(default_worktree_id),
                "layout": json.dumps(layout or {}),
            },
        )
        row = await cursor.fetchone()
        assert row is not None
        return _canvas_from_row(row)

    async def update_canvas(
        self,
        canvas_id: CanvasId,
        *,
        owner: str = "local",
        name: str | None = None,
        default_worktree_id: WorktreeId | None = None,
        layout: dict[str, Any] | None = None,
        archived: bool | None = None,
    ) -> Canvas | None:
        cursor = await self._conn.execute(
            """
            UPDATE canvas
            SET name = COALESCE(%(name)s, name),
                default_worktree_id = COALESCE(%(default_worktree_id)s, default_worktree_id),
                layout = COALESCE(%(layout)s::jsonb, layout),
                archived = COALESCE(%(archived)s, archived),
                updated_at = now()
            WHERE canvas_id = %(canvas_id)s AND owner = %(owner)s
            RETURNING canvas_id, space_id, owner, name, default_worktree_id, layout,
                      layout_version, archived, created_at, updated_at
            """,
            {
                "canvas_id": canvas_id.into_uuid(),
                "owner": owner,
                "name": name,
                "default_worktree_id": _uuid_or_none(default_worktree_id),
                "layout": json.dumps(layout) if layout is not None else None,
                "archived": archived,
            },
        )
        row = await cursor.fetchone()
        return _canvas_from_row(row) if row is not None else None

    async def _find_detection(
        self, detection: DetectedSpace, *, owner: str
    ) -> SpaceSnapshot | None:
        space = await self._lookup_space_for_detection(detection, owner=owner)
        if space is None:
            return None
        return await self.get_space_snapshot(space.space_id, owner=owner)

    async def _lookup_space_for_detection(
        self,
        detection: DetectedSpace,
        *,
        owner: str,
    ) -> Space | None:
        if detection.repo_instance_key is not None:
            cursor = await self._conn.execute(
                """
                SELECT s.space_id, s.owner, s.name, s.archived, s.created_at, s.updated_at
                FROM space AS s
                JOIN space_git_identity AS gi ON gi.space_id = s.space_id
                WHERE gi.repo_instance_key = %(repo_instance_key)s AND s.owner = %(owner)s
                """,
                {"repo_instance_key": detection.repo_instance_key, "owner": owner},
            )
            row = await cursor.fetchone()
            return _space_from_row(row) if row is not None else None

        first = detection.worktrees[0]
        cursor = await self._conn.execute(
            """
            SELECT s.space_id, s.owner, s.name, s.archived, s.created_at, s.updated_at
            FROM space AS s
            JOIN space_worktree AS w ON w.space_id = s.space_id
            WHERE s.owner = %(owner)s
              AND w.owner = %(owner)s
              AND w.workspace_slug = %(workspace_slug)s
              AND w.workspace_hash = %(workspace_hash)s
            """,
            {
                "owner": owner,
                "workspace_slug": first.workspace_slug,
                "workspace_hash": first.workspace_hash,
            },
        )
        row = await cursor.fetchone()
        return _space_from_row(row) if row is not None else None

    async def _insert_space(self, *, owner: str, name: str) -> Space:
        space_id = SpaceId.new()
        cursor = await self._conn.execute(
            """
            INSERT INTO space (space_id, owner, name)
            VALUES (%(space_id)s, %(owner)s, %(name)s)
            RETURNING space_id, owner, name, archived, created_at, updated_at
            """,
            {"space_id": space_id.into_uuid(), "owner": owner, "name": name},
        )
        row = await cursor.fetchone()
        assert row is not None
        return _space_from_row(row)

    async def _claim_git_space(self, detection: DetectedSpace, *, owner: str) -> Space:
        repo_instance_key = detection.repo_instance_key
        git_common_dir = detection.git_common_dir
        if repo_instance_key is None or git_common_dir is None:
            raise ValueError("git detection requires repo_instance_key and git_common_dir")

        space = await self._lookup_space_for_detection(detection, owner=owner)
        if space is not None:
            await self._touch_git_identity(space.space_id, detection)
            return space

        candidate = await self._insert_space(owner=owner, name=detection.name)
        cursor = await self._conn.execute(
            """
            INSERT INTO space_git_identity (space_id, repo_instance_key, git_common_dir)
            VALUES (%(space_id)s, %(repo_instance_key)s, %(git_common_dir)s)
            ON CONFLICT (repo_instance_key) DO NOTHING
            RETURNING space_id
            """,
            {
                "space_id": candidate.space_id.into_uuid(),
                "repo_instance_key": repo_instance_key,
                "git_common_dir": str(git_common_dir),
            },
        )
        claimed = await cursor.fetchone()
        if claimed is not None:
            return candidate

        await self._delete_space(candidate.space_id, owner=owner)
        space = await self._lookup_space_for_detection(detection, owner=owner)
        if space is None:
            raise RuntimeError("space identity claim lost but no existing space found")
        await self._touch_git_identity(space.space_id, detection)
        return space

    async def _touch_git_identity(self, space_id: SpaceId, detection: DetectedSpace) -> None:
        repo_instance_key = detection.repo_instance_key
        git_common_dir = detection.git_common_dir
        if repo_instance_key is None or git_common_dir is None:
            raise ValueError("git detection requires repo_instance_key and git_common_dir")

        await self._conn.execute(
            """
            UPDATE space_git_identity
            SET git_common_dir = %(git_common_dir)s, detected_at = now()
            WHERE space_id = %(space_id)s AND repo_instance_key = %(repo_instance_key)s
            """,
            {
                "space_id": space_id.into_uuid(),
                "repo_instance_key": repo_instance_key,
                "git_common_dir": str(git_common_dir),
            },
        )

    async def _delete_space(self, space_id: SpaceId, *, owner: str) -> None:
        await self._conn.execute(
            """
            DELETE FROM space
            WHERE space_id = %(space_id)s AND owner = %(owner)s
            """,
            {"space_id": space_id.into_uuid(), "owner": owner},
        )

    async def _upsert_worktree(
        self,
        space_id: SpaceId,
        detected: DetectedWorktree,
        *,
        owner: str,
    ) -> Worktree:
        cursor = await self._conn.execute(
            """
            INSERT INTO space_worktree (
                worktree_id, space_id, owner, path, workspace_slug, workspace_hash,
                branch_name, head_oid, is_primary, missing, archived
            ) VALUES (
                %(worktree_id)s, %(space_id)s, %(owner)s, %(path)s, %(workspace_slug)s,
                %(workspace_hash)s, %(branch_name)s, %(head_oid)s, %(is_primary)s,
                %(missing)s, false
            )
            ON CONFLICT (owner, workspace_slug, workspace_hash) DO UPDATE SET
                space_id = EXCLUDED.space_id,
                path = EXCLUDED.path,
                branch_name = EXCLUDED.branch_name,
                head_oid = EXCLUDED.head_oid,
                is_primary = EXCLUDED.is_primary,
                missing = EXCLUDED.missing,
                archived = false,
                detected_at = now(),
                updated_at = now()
            RETURNING worktree_id, space_id, owner, path, workspace_slug, workspace_hash,
                      branch_name, head_oid, is_primary, missing, archived,
                      detected_at, created_at, updated_at
            """,
            {
                "worktree_id": WorktreeId.new().into_uuid(),
                "space_id": space_id.into_uuid(),
                "owner": owner,
                "path": str(detected.path),
                "workspace_slug": detected.workspace_slug,
                "workspace_hash": detected.workspace_hash,
                "branch_name": detected.branch_name,
                "head_oid": detected.head_oid,
                "is_primary": detected.is_primary,
                "missing": detected.missing,
            },
        )
        row = await cursor.fetchone()
        assert row is not None
        return _worktree_from_row(row)

    async def _mark_missing_worktrees(
        self,
        space_id: SpaceId,
        *,
        owner: str,
        active_paths: Sequence[str],
    ) -> None:
        await self._conn.execute(
            """
            UPDATE space_worktree
            SET missing = true, is_primary = false, updated_at = now()
            WHERE space_id = %(space_id)s
              AND owner = %(owner)s
              AND path IS NOT NULL
              AND NOT (path = ANY(%(active_paths)s::text[]))
            """,
            {"space_id": space_id.into_uuid(), "owner": owner, "active_paths": list(active_paths)},
        )

    def _write_cache(self, snapshot: SpaceSnapshot) -> None:
        root = self._storage_dir / "spaces" / str(snapshot.space.space_id)
        _atomic_json(root / "space.json", _space_cache_payload(snapshot))
        _atomic_json(
            root / "worktrees.json", [item.model_dump(mode="json") for item in snapshot.worktrees]
        )


def _space_from_row(row: Mapping[str, Any]) -> Space:
    return Space(
        space_id=SpaceId.from_uuid(row["space_id"]),
        owner=row["owner"],
        name=row["name"],
        archived=row["archived"],
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _identity_from_row(row: Mapping[str, Any]) -> SpaceGitIdentity | None:
    if row.get("repo_instance_key") is None:
        return None
    return SpaceGitIdentity(
        space_id=SpaceId.from_uuid(row["space_id"]),
        repo_instance_key=row["repo_instance_key"],
        git_common_dir=row["git_common_dir"],
        detected_at=row.get("detected_at"),
    )


def _worktree_from_row(row: Mapping[str, Any]) -> Worktree:
    return Worktree(
        worktree_id=WorktreeId.from_uuid(row["worktree_id"]),
        space_id=SpaceId.from_uuid(row["space_id"]),
        owner=row["owner"],
        path=row["path"],
        workspace_slug=row["workspace_slug"],
        workspace_hash=row["workspace_hash"],
        branch_name=row["branch_name"],
        head_oid=row["head_oid"],
        is_primary=row["is_primary"],
        missing=row["missing"],
        archived=row["archived"],
        detected_at=row.get("detected_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _canvas_from_row(row: Mapping[str, Any]) -> Canvas:
    return Canvas(
        canvas_id=CanvasId.from_uuid(row["canvas_id"]),
        space_id=SpaceId.from_uuid(row["space_id"]),
        owner=row["owner"],
        name=row["name"],
        default_worktree_id=(
            WorktreeId.from_uuid(row["default_worktree_id"])
            if row["default_worktree_id"] is not None
            else None
        ),
        layout=row["layout"] or {},
        layout_version=row["layout_version"],
        archived=row["archived"],
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _uuid_or_none(value: WorktreeId | None) -> object | None:
    return value.into_uuid() if value is not None else None


def _space_cache_payload(snapshot: SpaceSnapshot) -> dict[str, object]:
    payload = snapshot.space.model_dump(mode="json")
    payload["git_identity"] = (
        snapshot.git_identity.model_dump(mode="json") if snapshot.git_identity is not None else None
    )
    return payload


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
