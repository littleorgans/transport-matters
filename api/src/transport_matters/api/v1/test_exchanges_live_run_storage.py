"""Regression tests for live run exchange reads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from httpx import ASGITransport, AsyncClient

from transport_matters.main import create_app
from transport_matters.storage.base import ExchangeArtifacts
from transport_matters.storage.disk import DiskStorageBackend
from transport_matters.test_run_manager import (
    PreparedRunHarness,
    PtyHarness,
    make_manager,
    patch_pty_teardown,
    spawn_run,
)

from .test_exchanges_support import make_index_entry, make_ir

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


async def test_live_run_reads_exchange_written_by_distinct_storage_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    storage_root = tmp_path / "live-run-storage"
    pty = PtyHarness()
    patch_pty_teardown(monkeypatch, pty)
    manager = make_manager(storage_root, pty, PreparedRunHarness(storage_root))
    run = await spawn_run(manager, workspace)
    app = create_app()
    app.state.run_manager = manager
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            initial = await client.get(f"/v1/runs/{run.run_id}/exchanges")
            assert initial.status_code == 200
            assert initial.json() == []

            writer = DiskStorageBackend(root=run.spawn_spec.storage_dir)
            entry = make_index_entry("ex-live", run_id=run.run_id)
            await writer.append_index(entry)
            await writer.write_exchange(
                entry.id,
                ExchangeArtifacts(
                    request_raw=b'{"model":"claude-sonnet-4-20250514","max_tokens":1024}',
                    request_ir=make_ir(),
                ),
            )

            detail = await client.get(f"/v1/runs/{run.run_id}/exchanges/ex-live")
            assert detail.status_code == 200
            assert detail.json()["entry"]["id"] == "ex-live"

            listing = await client.get(f"/v1/runs/{run.run_id}/exchanges")
            assert listing.status_code == 200
            assert [row["id"] for row in listing.json()] == ["ex-live"]
    finally:
        await manager.close()
