from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

import pytest

from transport_matters.api.v1 import run_routes
from transport_matters.api.v1.test_run_routes import BACKEND_ORIGIN, ManagedRunHarness, _client, _http_headers
from transport_matters.captured_run import CLAUDE_HARNESS_NAME
from transport_matters.run_manager import ManagedRunView, RunFilters, RunState, SpawnRun
from transport_matters.space.models import ResolvedWorktree, SpaceId, WorktreeId

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi import Request


class _FilteringRunManager:
    def __init__(self, views: list[ManagedRunView]) -> None:
        self.views = views
        self.calls: list[RunFilters | None] = []

    def list(self, filters: RunFilters | None = None) -> list[ManagedRunView]:
        self.calls.append(filters)
        views = self.views
        if filters is not None and filters.states is not None:
            views = [view for view in views if view.state in filters.states]
        return views


@pytest.mark.asyncio
async def test_list_runs_running_filter_includes_starting_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    view = _run_view(tmp_path, state=RunState.STARTING)
    manager = _FilteringRunManager([view])
    monkeypatch.setattr(run_routes, "_run_manager", lambda _: manager)

    running = await run_routes.list_runs(
        cast("Request", object()),
        state="RUNNING",
        space_id=None,
        worktree_id=None,
        limit=50,
        cursor=None,
    )
    running_items = cast("list[dict[str, object]]", running["items"])
    assert [item["runId"] for item in running_items] == ["run-1"]
    assert running_items[0]["state"] == "RUNNING"
    assert manager.calls[0] == RunFilters(states=frozenset({RunState.STARTING, RunState.RUNNING}))

    terminating = await run_routes.list_runs(
        cast("Request", object()),
        state="TERMINATING",
        space_id=None,
        worktree_id=None,
        limit=50,
        cursor=None,
    )
    terminating_items = cast("list[dict[str, object]]", terminating["items"])
    assert terminating_items == []
    assert manager.calls[1] == RunFilters(states=frozenset({RunState.TERMINATING}))


def test_list_runs_filters_by_space_and_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    harness = ManagedRunHarness(tmp_path, monkeypatch)
    first_space = SpaceId.from_uuid(UUID("11111111-1111-4111-8111-111111111111"))
    second_space = SpaceId.from_uuid(UUID("33333333-3333-4333-8333-333333333333"))
    first_worktree = WorktreeId.from_uuid(UUID("22222222-2222-4222-8222-222222222222"))
    second_worktree = WorktreeId.from_uuid(UUID("44444444-4444-4444-8444-444444444444"))
    first = asyncio.run(
        harness.manager.spawn(
            SpawnRun(
                harness=CLAUDE_HARNESS_NAME,
                resolved_worktree=_resolved(
                    tmp_path, space_id=first_space, worktree_id=first_worktree
                ),
            )
        )
    )
    asyncio.run(
        harness.manager.spawn(
            SpawnRun(
                harness=CLAUDE_HARNESS_NAME,
                resolved_worktree=_resolved(
                    tmp_path, space_id=second_space, worktree_id=second_worktree
                ),
            )
        )
    )
    client = _client(monkeypatch, tmp_path)

    with client:
        by_space = client.get(
            "/v1/runs",
            params={"spaceId": str(first_space)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()
        by_worktree = client.get(
            "/v1/runs",
            params={"worktreeId": str(first_worktree)},
            headers=_http_headers(BACKEND_ORIGIN),
        ).json()

    assert [item["runId"] for item in by_space["items"]] == [first.run_id]
    assert [item["runId"] for item in by_worktree["items"]] == [first.run_id]


def _resolved(tmp_path: Path, *, space_id: SpaceId, worktree_id: WorktreeId) -> ResolvedWorktree:
    return ResolvedWorktree(
        space_id=space_id,
        worktree_id=worktree_id,
        cwd=str(tmp_path),
        workspace_slug="workspace",
        workspace_hash="hash1",
        missing=False,
        archived=False,
    )


def _run_view(tmp_path: Path, *, state: RunState) -> ManagedRunView:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    return ManagedRunView(
        run_id="run-1",
        harness="codex",
        cwd=tmp_path,
        space_id=SpaceId.from_uuid(UUID("11111111-1111-4111-8111-111111111111")),
        worktree_id=WorktreeId.from_uuid(UUID("22222222-2222-4222-8222-222222222222")),
        storage_dir=tmp_path / "run-1",
        proxy_port=19001,
        web_port=None,
        native_session_id=None,
        state=state,
        created_at=now,
        started_at=now,
        updated_at=now,
        viewer_count=0,
        viewerless_since=now,
        exit_code=None,
        end_reason=None,
        error=None,
        scrollback_bytes=0,
        scrollback_limit_bytes=0,
    )
