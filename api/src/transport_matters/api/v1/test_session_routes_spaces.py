from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from transport_matters.api.v1.session_test_support import session_client as _client
from transport_matters.session.async_dao import AsyncSessionDao
from transport_matters.session.pool import create_async_pool
from transport_matters.session.test_foundation import root_session
from transport_matters.space.models import SpaceId, WorktreeId

if TYPE_CHECKING:
    from transport_matters.session.testing import TestDb

SPACE_ID = SpaceId.from_uuid(UUID("11111111-1111-4111-8111-111111111111"))
WORKTREE_ID = WorktreeId.from_uuid(UUID("22222222-2222-4222-8222-222222222222"))
OTHER_WORKTREE_ID = WorktreeId.from_uuid(UUID("33333333-3333-4333-8333-333333333333"))
OTHER_SPACE_ID = SpaceId.from_uuid(UUID("44444444-4444-4444-8444-444444444444"))
OTHER_SPACE_WORKTREE_ID = WorktreeId.from_uuid(UUID("55555555-5555-4555-8555-555555555555"))


async def _seed_space_sessions(test_db: TestDb) -> None:
    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        dao = AsyncSessionDao(conn)
        await dao.upsert_session(
            root_session("s1", native_session_id="native-s1").model_copy(
                update={
                    "cwd": "/workspace/one",
                    "workspace_slug": "workspace",
                    "workspace_hash": "one",
                    "space_id": SPACE_ID,
                    "worktree_id": WORKTREE_ID,
                }
            )
        )
        await dao.upsert_session(
            root_session("s2", native_session_id="native-s2").model_copy(
                update={
                    "cwd": "/workspace/two",
                    "workspace_slug": "workspace",
                    "workspace_hash": "two",
                    "space_id": SPACE_ID,
                    "worktree_id": OTHER_WORKTREE_ID,
                }
            )
        )
        await dao.upsert_session(
            root_session("s3", native_session_id="native-s3").model_copy(
                update={
                    "cwd": "/other/space",
                    "workspace_slug": "other",
                    "workspace_hash": "space",
                    "space_id": OTHER_SPACE_ID,
                    "worktree_id": OTHER_SPACE_WORKTREE_ID,
                }
            )
        )


async def _seed_empty_cwd_session(test_db: TestDb) -> None:
    async with (
        create_async_pool(test_db.database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        await AsyncSessionDao(conn).upsert_session(
            root_session("legacy", native_session_id="native-legacy").model_copy(
                update={
                    "cwd": "",
                    "workspace_slug": "legacy",
                    "workspace_hash": "workspace",
                    "space_id": None,
                    "worktree_id": None,
                }
            )
        )


@pytest.mark.asyncio
async def test_session_list_emits_space_ids_as_camel_case(test_db: TestDb) -> None:
    await _seed_space_sessions(test_db)

    async with _client(test_db) as client:
        response = await client.get(
            "/v1/sessions",
            params={"worktreeId": str(WORKTREE_ID)},
        )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["spaceId"] == str(SPACE_ID)
    assert item["worktreeId"] == str(WORKTREE_ID)
    assert "space_id" not in item
    assert "worktree_id" not in item
    assert item["legacyGroup"] is None


@pytest.mark.asyncio
async def test_empty_cwd_session_is_legacy_unassigned(test_db: TestDb) -> None:
    await _seed_empty_cwd_session(test_db)

    async with _client(test_db) as client:
        response = await client.get(
            "/v1/sessions",
            params={"workspaceId": "legacy/workspace"},
        )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["sessionId"] == "legacy"
    assert item["workspaceId"] == "legacy/workspace"
    assert item["spaceId"] is None
    assert item["worktreeId"] is None
    assert item["legacyGroup"] == "unassigned"


@pytest.mark.asyncio
async def test_session_list_filters_by_space_id(test_db: TestDb) -> None:
    await _seed_space_sessions(test_db)

    async with _client(test_db) as client:
        response = await client.get("/v1/sessions", params={"spaceId": str(SPACE_ID)})

    assert response.status_code == 200
    assert {item["sessionId"] for item in response.json()["items"]} == {"s1", "s2"}


@pytest.mark.asyncio
async def test_session_list_filters_by_worktree_id(test_db: TestDb) -> None:
    await _seed_space_sessions(test_db)

    async with _client(test_db) as client:
        response = await client.get(
            "/v1/sessions",
            params={"worktreeId": str(WORKTREE_ID)},
        )

    assert response.status_code == 200
    assert [item["sessionId"] for item in response.json()["items"]] == ["s1"]


@pytest.mark.asyncio
async def test_workspace_id_filter_still_finds_empty_cwd_legacy_sessions(
    test_db: TestDb,
) -> None:
    await _seed_empty_cwd_session(test_db)

    async with _client(test_db) as client:
        response = await client.get(
            "/v1/sessions",
            params={"workspaceId": "legacy/workspace"},
        )

    assert response.status_code == 200
    assert [item["sessionId"] for item in response.json()["items"]] == ["legacy"]
    assert response.json()["items"][0]["legacyGroup"] == "unassigned"
