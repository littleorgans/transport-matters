from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from transport_matters.session.pool import create_async_pool
from transport_matters.space.store import SpaceStore

if TYPE_CHECKING:
    from pathlib import Path

    from transport_matters.session.testing import TestDb


@pytest.mark.asyncio
async def test_resolve_session_cwd_uses_existing_worktree_for_present_path(
    test_db: TestDb,
    tmp_path: Path,
) -> None:
    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        store = SpaceStore(conn, storage_dir=tmp_path / "storage")
        resolved = await store.resolve_session_cwd(str(tmp_path), owner="local")
        again = await store.resolve_session_cwd(str(tmp_path), owner="local")

    assert resolved.cwd == str(tmp_path)
    assert resolved.missing is False
    assert again.space_id == resolved.space_id
    assert again.worktree_id == resolved.worktree_id


@pytest.mark.asyncio
async def test_resolve_session_cwd_creates_missing_worktree_for_deleted_path(
    test_db: TestDb,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "deleted" / "project"

    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        store = SpaceStore(conn, storage_dir=tmp_path / "storage")
        resolved = await store.resolve_session_cwd(str(missing), owner="local")
        again = await store.resolve_session_cwd(str(missing), owner="local")
        worktree = await store.get_worktree(resolved.worktree_id, owner="local")

    assert resolved.cwd == str(missing)
    assert resolved.missing is True
    assert resolved.archived is False
    assert again.space_id == resolved.space_id
    assert again.worktree_id == resolved.worktree_id
    assert worktree is not None
    assert worktree.missing is True
    assert worktree.branch_name is None
    assert worktree.head_oid is None
    assert worktree.is_primary is False
