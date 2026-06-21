from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from transport_matters.captured_run import WEB_RUNTIME_EMBEDDED
from transport_matters.run_manager import RunFilters, SpawnRun
from transport_matters.space.models import ResolvedWorktree, SpaceId, WorktreeId
from transport_matters.test_run_manager import (
    PreparedRunHarness,
    PtyHarness,
    make_manager,
    patch_pty_teardown,
)

if TYPE_CHECKING:
    from pathlib import Path


def _resolved(tmp_path: Path) -> ResolvedWorktree:
    return ResolvedWorktree(
        space_id=SpaceId.from_uuid(UUID("11111111-1111-4111-8111-111111111111")),
        worktree_id=WorktreeId.from_uuid(UUID("22222222-2222-4222-8222-222222222222")),
        cwd=str(tmp_path),
        workspace_slug="workspace",
        workspace_hash="hash1",
        missing=False,
        archived=False,
    )


@pytest.mark.asyncio
async def test_run_manager_threads_resolved_worktree_into_run_view(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pty = PtyHarness()
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared, shared_proxy_manager=object())
    resolved = _resolved(tmp_path)

    run = await manager.spawn(
        SpawnRun(
            harness="claude",
            resolved_worktree=resolved,
            web_runtime=WEB_RUNTIME_EMBEDDED,
            start_on_attach=False,
        )
    )
    view = run.view()

    assert run.cwd == tmp_path
    assert run.space_id == resolved.space_id
    assert run.worktree_id == resolved.worktree_id
    assert view.space_id == resolved.space_id
    assert view.worktree_id == resolved.worktree_id
    assert view.cwd == tmp_path


@pytest.mark.asyncio
async def test_run_manager_filters_by_space_and_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pty = PtyHarness()
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared, shared_proxy_manager=object())
    resolved = _resolved(tmp_path)
    other = resolved.model_copy(
        update={"worktree_id": WorktreeId.from_uuid(UUID("33333333-3333-4333-8333-333333333333"))}
    )

    first = await manager.spawn(
        SpawnRun(
            harness="claude",
            resolved_worktree=resolved,
            web_runtime=WEB_RUNTIME_EMBEDDED,
        )
    )
    await manager.spawn(
        SpawnRun(
            harness="claude",
            resolved_worktree=other,
            web_runtime=WEB_RUNTIME_EMBEDDED,
        )
    )

    assert [item.run_id for item in manager.list(RunFilters(space_id=resolved.space_id))] == [
        first.run_id,
        next(item.run_id for item in manager.list() if item.run_id != first.run_id),
    ]
    assert [item.run_id for item in manager.list(RunFilters(worktree_id=resolved.worktree_id))] == [
        first.run_id
    ]
