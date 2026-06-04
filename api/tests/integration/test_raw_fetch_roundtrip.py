"""Cross-system regression + real-run proof (roadtest2 #1): GET /api/index/exchanges/{id}/raw
must stream the tier-1 bytes the storage backend actually wrote, even when the backend root is
workspace-scoped (``settings.storage_dir``) rather than the global default.

A road-tested live claude capture 404'd ("request raw bytes not found") because ``build_wire_job``
recomputed ``raw_dir`` on the global default root while the artifacts lived under
``~/.transport-matters/workspaces/<slug>/<hash>/<session>/`` — a dangling absolute pointer. This
test reproduces that shape end-to-end through the real FastAPI route: tier-1 under a non-default
root, tier-2 index pointing back to it, then an in-process HTTP GET that must return 200 + bytes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from httpx import ASGITransport, AsyncClient

import transport_matters.api.v1.index_routes as index_routes
from transport_matters.index.ingest import RunFacts, make_index_sink
from transport_matters.index.writer import IndexWriter
from transport_matters.main import create_app
from transport_matters.storage.base import ExchangeArtifacts
from transport_matters.storage.disk import DiskStorageBackend
from transport_matters.storage.test_exchange_support import make_index_entry, make_request_ir

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_REQUEST_BYTES = b'{"req":"bytes"}'
_RESPONSE_BYTES = b'{"res":"bytes"}'


def _run_facts(cwd: Path) -> RunFacts:
    return RunFacts(
        run_id="run1",
        cwd=cwd,
        workspace_slug="slug",
        workspace_hash="hash",
        started_at="2026-06-05T00:00:00Z",
    )


async def test_raw_route_streams_bytes_under_workspace_scoped_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Tier-1 storage rooted at a NON-default, workspace-scoped directory (the road-test shape).
    ws_root = tmp_path / "workspaces" / "proj" / "hash" / "session"
    backend = DiskStorageBackend(root=ws_root)

    entry = make_index_entry()
    artifacts = ExchangeArtifacts(
        request_raw=_REQUEST_BYTES,
        request_ir=make_request_ir(session_id="sess-1"),
        response_raw=_RESPONSE_BYTES,
    )
    # Tier-1 write: bytes land under ws_root/<slug>-<id>/{request,response}.raw.
    await backend.persist_exchange(entry, artifacts)

    # Tier-2 ingest via the injected sink, told the backend's real (workspace-scoped) root.
    db_path = tmp_path / "index.db"
    writer = IndexWriter(str(db_path), flush_ms=5)
    writer.start()
    make_index_sink(writer, _run_facts(tmp_path), storage_root=backend.root)(entry, artifacts)
    writer.stop(drain=True)

    # Drive the REAL route with the read-only connection pointed at our fresh index.db.
    monkeypatch.setattr(index_routes, "index_db_path", lambda: db_path)
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        request_resp = await client.get(f"/api/index/exchanges/{entry.id}/raw?part=request")
        response_resp = await client.get(f"/api/index/exchanges/{entry.id}/raw?part=response")

    # The pointer must resolve to the persisted bytes — not the 404 the road-test hit.
    assert request_resp.status_code == 200
    assert request_resp.content == _REQUEST_BYTES
    assert response_resp.status_code == 200
    assert response_resp.content == _RESPONSE_BYTES
