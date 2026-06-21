from __future__ import annotations

import json
from typing import TYPE_CHECKING

from transport_matters.session.pool import create_async_pool
from transport_matters.space.detection import DetectedSpace, DetectedWorktree, repo_instance_key
from transport_matters.space.store import SpaceStore
from transport_matters.workspace import workspace_id

if TYPE_CHECKING:
    from pathlib import Path

    from transport_matters.session.testing import TestDb


def _detected_worktree(
    path: Path,
    *,
    branch: str | None = None,
    head: str | None = None,
    is_primary: bool = False,
) -> DetectedWorktree:
    workspace = workspace_id(path)
    return DetectedWorktree(
        path=path.resolve(strict=False),
        workspace_slug=workspace.slug,
        workspace_hash=workspace.hash,
        branch_name=branch,
        head_oid=head,
        is_primary=is_primary,
    )


def _git_detection(root: Path, *worktrees: Path) -> DetectedSpace:
    common_dir = root / ".git"
    detected_worktrees = [_detected_worktree(root, branch="main", head="abc123", is_primary=True)]
    detected_worktrees.extend(
        _detected_worktree(path, branch=f"feature-{index}", head="abc123")
        for index, path in enumerate(worktrees, start=1)
    )
    return DetectedSpace(
        name="repo",
        primary_path=root.resolve(strict=False),
        repo_instance_key=repo_instance_key(common_dir),
        git_common_dir=common_dir.resolve(strict=False),
        worktrees=tuple(detected_worktrees),
    )


async def test_store_mints_git_space_reuses_identity_reconciles_and_writes_cache(
    test_db: TestDb,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    linked = tmp_path / "linked"
    repo.mkdir()
    linked.mkdir()
    storage = tmp_path / "storage"

    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        store = SpaceStore(conn, storage_dir=storage)
        first = await store.upsert_detection(_git_detection(repo, linked))
        second = await store.upsert_detection(_git_detection(repo))
        resolved = await store.resolve_worktree(first.worktrees[0].worktree_id)
        fetched_worktree = await store.get_worktree(first.worktrees[0].worktree_id)

    assert second.space.space_id == first.space.space_id
    assert second.git_identity is not None
    assert second.git_identity.repo_instance_key == repo_instance_key(repo / ".git")
    assert second.git_identity.space_id == first.space.space_id
    by_path = {item.path: item for item in second.worktrees}
    assert by_path[str(repo.resolve())].is_primary is True
    assert by_path[str(repo.resolve())].branch_name == "main"
    assert by_path[str(repo.resolve())].head_oid == "abc123"
    assert by_path[str(linked.resolve())].missing is True
    assert resolved is not None
    assert fetched_worktree is not None
    assert fetched_worktree.worktree_id == first.worktrees[0].worktree_id
    assert resolved.space_id == first.space.space_id
    assert resolved.worktree_id == first.worktrees[0].worktree_id
    assert resolved.cwd == str(repo.resolve())

    cache_root = storage / "spaces" / str(first.space.space_id)
    assert json.loads((cache_root / "space.json").read_text(encoding="utf-8"))["space_id"] == str(
        first.space.space_id
    )
    cached_worktrees = json.loads((cache_root / "worktrees.json").read_text(encoding="utf-8"))
    assert {item["path"] for item in cached_worktrees} == {
        str(repo.resolve()),
        str(linked.resolve()),
    }
    assert [item for item in cached_worktrees if item["is_primary"]] == [
        next(item for item in cached_worktrees if item["path"] == str(repo.resolve()))
    ]


async def test_plain_directory_uses_no_git_identity_row(test_db: TestDb, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    detection = DetectedSpace(
        name="plain",
        primary_path=plain.resolve(),
        repo_instance_key=None,
        git_common_dir=None,
        worktrees=(_detected_worktree(plain, is_primary=True),),
    )

    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        snapshot = await SpaceStore(conn, storage_dir=tmp_path / "storage").upsert_detection(
            detection
        )
        cursor = await conn.execute("SELECT count(*) FROM space_git_identity")
        row = await cursor.fetchone()
        assert row is not None
        identity_count = row["count"]

    assert snapshot.git_identity is None
    assert identity_count == 0
    assert snapshot.worktrees[0].path == str(plain.resolve())
    assert snapshot.worktrees[0].is_primary is True


async def test_resolve_cwd_can_lookup_without_create(test_db: TestDb, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        store = SpaceStore(conn, storage_dir=tmp_path / "storage")
        assert await store.resolve_cwd(plain, create=False) is None
        created = await store.resolve_cwd(plain, create=True)
        found = await store.resolve_cwd(plain, create=False)

    assert created is not None
    assert found is not None
    assert found.space.space_id == created.space.space_id
    assert found.worktrees[0].worktree_id == created.worktrees[0].worktree_id


async def test_canvas_methods_are_owner_scoped(test_db: TestDb, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        store = SpaceStore(conn, storage_dir=tmp_path / "storage")
        snapshot = await store.resolve_cwd(plain, create=True)
        assert snapshot is not None
        canvas = await store.create_canvas(
            snapshot.space.space_id,
            owner="local",
            name="Main canvas",
            default_worktree_id=snapshot.worktrees[0].worktree_id,
            layout={"panes": []},
        )
        hidden = await store.get_space_snapshot(snapshot.space.space_id, owner="other")
        canvases = await store.list_canvases(snapshot.space.space_id, owner="local")
        updated = await store.update_canvas(canvas.canvas_id, owner="local", name="Renamed")

    assert hidden is None
    assert [item.canvas_id for item in canvases] == [canvas.canvas_id]
    assert updated is not None
    assert updated.name == "Renamed"
