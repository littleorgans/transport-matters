from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from transport_matters.session.backfill import backfill_session_spaces
from transport_matters.space.models import ResolvedWorktree, SpaceId, WorktreeId

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class BackfillCandidate:
    session_id: str
    owner: str
    workspace_id: str | None
    cwd: str


class FakeSessionDao:
    def __init__(self, candidates: list[BackfillCandidate]) -> None:
        self.candidates = candidates
        self.updates: list[tuple[str, SpaceId, WorktreeId]] = []

    async def list_sessions_missing_space_identity(
        self, *, owner: str, limit: int
    ) -> list[BackfillCandidate]:
        return [candidate for candidate in self.candidates if candidate.owner == owner][:limit]

    async def update_session_space_identity(
        self,
        *,
        owner: str,
        session_id: str,
        space_id: SpaceId,
        worktree_id: WorktreeId,
    ) -> None:
        self.updates.append((session_id, space_id, worktree_id))
        self.candidates = [
            candidate for candidate in self.candidates if candidate.session_id != session_id
        ]


class FakeSpaceStore:
    def __init__(self, resolved: ResolvedWorktree) -> None:
        self.resolved = resolved
        self.cwd_calls: list[str] = []

    async def resolve_session_cwd(self, cwd: str, *, owner: str) -> ResolvedWorktree:
        self.cwd_calls.append(cwd)
        return self.resolved


def _resolved(cwd: str, *, missing: bool = False) -> ResolvedWorktree:
    return ResolvedWorktree(
        space_id=SpaceId.from_uuid(UUID("11111111-1111-4111-8111-111111111111")),
        worktree_id=WorktreeId.from_uuid(UUID("22222222-2222-4222-8222-222222222222")),
        cwd=cwd,
        workspace_slug="workspace",
        workspace_hash="hash1",
        missing=missing,
        archived=False,
    )


@pytest.mark.asyncio
async def test_backfill_writes_space_identity_for_real_cwd(tmp_path: Path) -> None:
    cwd = str(tmp_path)
    dao = FakeSessionDao([BackfillCandidate("s1", "local", "legacy", cwd)])
    store = FakeSpaceStore(_resolved(cwd))

    result = await backfill_session_spaces(session_dao=dao, space_store=store, owner="local")

    assert store.cwd_calls == [cwd]
    assert dao.updates == [("s1", store.resolved.space_id, store.resolved.worktree_id)]
    assert result.scanned == 1
    assert result.resolved == 1
    assert result.missing == 0
    assert result.legacy_unassigned == 0


@pytest.mark.asyncio
async def test_backfill_leaves_empty_cwd_unassigned() -> None:
    dao = FakeSessionDao([BackfillCandidate("legacy", "local", "old-workspace", "")])
    store = FakeSpaceStore(_resolved("/should/not/be/used"))

    result = await backfill_session_spaces(session_dao=dao, space_store=store, owner="local")

    assert store.cwd_calls == []
    assert dao.updates == []
    assert result.scanned == 1
    assert result.resolved == 0
    assert result.missing == 0
    assert result.legacy_unassigned == 1
