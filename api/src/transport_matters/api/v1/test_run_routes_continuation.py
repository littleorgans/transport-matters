from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from transport_matters import env_keys
from transport_matters.api.v1.test_run_routes_support import (
    BACKEND_ORIGIN,
    ManagedRunHarness,
    _http_headers,
)
from transport_matters.session.async_dao import AsyncSessionDao
from transport_matters.session.pool import create_async_pool
from transport_matters.session.test_foundation import event, root_session

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager
    from pathlib import Path

    import pytest
    from fastapi.testclient import TestClient

    from transport_matters.session.testing import TestDb


def test_post_continuation_threads_lineage_context_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    test_db: TestDb,
    lifespan_client: Callable[[], AbstractContextManager[TestClient]],
) -> None:
    asyncio.run(_seed_continuation_parent(test_db.database_url))
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    monkeypatch.setenv(env_keys.CWD, str(tmp_path))
    body = {
        "harness": "claude",
        "worktreeId": str(harness.worktree_id),
        "continueFromSessionId": "parent-session",
        "idempotencyKey": "resume-click-1",
    }

    with lifespan_client() as client:
        first = client.post("/v1/runs", json=body, headers=_http_headers(BACKEND_ORIGIN))
        second = client.post("/v1/runs", json=body, headers=_http_headers(BACKEND_ORIGIN))

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["run"]["runId"] == first.json()["run"]["runId"]
    assert len(harness.prepared.requests) == 1
    captured = harness.prepared.requests[0]
    assert captured.launch_fields == {
        "continue_from_session_id": "parent-session",
        "parent_session_id": "parent-session",
        "forked_at_seq": 1,
        "session_purpose": "continuation",
        "resume_context": {
            "firstUserPrompt": "first prompt",
            "lastAgentMessage": "last answer",
            "transcriptRef": "parent-session",
        },
    }


def test_post_continuation_returns_not_found_for_foreign_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    test_db: TestDb,
    lifespan_client: Callable[[], AbstractContextManager[TestClient]],
) -> None:
    asyncio.run(_seed_continuation_parent(test_db.database_url, owner="other"))
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    monkeypatch.setenv(env_keys.CWD, str(tmp_path))

    with lifespan_client() as client:
        response = client.post(
            "/v1/runs",
            json={
                "harness": "claude",
                "worktreeId": str(harness.worktree_id),
                "continueFromSessionId": "parent-session",
                "idempotencyKey": "resume-click-1",
            },
            headers=_http_headers(BACKEND_ORIGIN),
        )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "session_not_found"
    assert harness.manager.list() == []
    assert harness.prepared.requests == []


async def _seed_continuation_parent(database_url: str, *, owner: str = "local") -> None:
    async with (
        create_async_pool(database_url, min_size=1, max_size=2) as pool,
        pool.connection() as conn,
    ):
        dao = AsyncSessionDao(conn)
        await dao.upsert_session(
            root_session("parent-session", native_session_id="native-parent").model_copy(
                update={"owner": owner}
            )
        )
        await dao.insert_event(
            event(0, session_id="parent-session", search_text="first prompt").model_copy(
                update={
                    "role": "user",
                    "ir": {"parts": [{"type": "text", "text": "first prompt"}]},
                }
            )
        )
        await dao.insert_event(
            event(1, session_id="parent-session", search_text="last answer").model_copy(
                update={"role": "assistant"}
            )
        )
        await dao.insert_event(
            event(2, session_id="parent-session", search_text="sidechain").model_copy(
                update={"role": "assistant", "is_sidechain": True}
            )
        )
