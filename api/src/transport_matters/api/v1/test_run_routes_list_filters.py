from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import pytest

from transport_matters.api.v1 import run_routes
from transport_matters.run_manager import ManagedRunView, RunFilters, RunState

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
        cast("Request", object()), state="RUNNING", limit=50, cursor=None
    )
    running_items = cast("list[dict[str, object]]", running["items"])
    assert [item["runId"] for item in running_items] == ["run-1"]
    assert running_items[0]["state"] == "RUNNING"
    assert manager.calls[0] == RunFilters(states=frozenset({RunState.STARTING, RunState.RUNNING}))

    terminating = await run_routes.list_runs(
        cast("Request", object()), state="TERMINATING", limit=50, cursor=None
    )
    terminating_items = cast("list[dict[str, object]]", terminating["items"])
    assert terminating_items == []
    assert manager.calls[1] == RunFilters(states=frozenset({RunState.TERMINATING}))


def _run_view(tmp_path: Path, *, state: RunState) -> ManagedRunView:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    return ManagedRunView(
        run_id="run-1",
        harness="codex",
        cwd=tmp_path,
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
