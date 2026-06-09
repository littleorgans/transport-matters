from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

from transport_matters.api.v1 import captured_terminal, run_routes
from transport_matters.captured_run import CLAUDE_CLIENT_NAME
from transport_matters.config import Settings
from transport_matters.test_run_manager import (
    PreparedRunHarness,
    PtyHarness,
    make_manager,
    patch_pty_teardown,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

    from transport_matters.run_manager import CapturedRunCli


def test_captured_spawn_request_requests_claude_nested_capture_only(tmp_path: Path) -> None:
    settings = Settings(cwd=tmp_path)

    request = run_routes.captured_spawn_request(
        cli=cast("CapturedRunCli", CLAUDE_CLIENT_NAME),
        cwd=None,
        cols=80,
        rows=24,
        settings=settings,
    )

    assert request.web_runtime == "external"
    assert request.web_port is None
    assert request.cwd == tmp_path


def test_ready_frame_omits_nested_web_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pty = PtyHarness()
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)

    async def build_frame() -> dict[str, object]:
        run = await manager.spawn(
            run_routes.captured_spawn_request(
                cli=cast("CapturedRunCli", CLAUDE_CLIENT_NAME),
                cwd=str(tmp_path),
                cols=80,
                rows=24,
                settings=Settings(cwd=tmp_path),
            )
        )
        attached = manager.attach(run.run_id, cols=80, rows=24)
        return captured_terminal._ready_frame(run, attached)

    frame = asyncio.run(build_frame())
    assert frame["type"] == "captured-run.ready"
    assert "webPort" not in frame
    asyncio.run(manager.close())
