from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from transport_matters.addon_runtime import CaptureRuntime
from transport_matters.index.adapters.base import FileTailSource, SessionBinding
from transport_matters.index.tailer import TailCursor, TranscriptTailer
from transport_matters.shared_proxy.binding import ProxyRunBinding
from transport_matters.shared_proxy.core import SharedProxyCore, SharedTranscriptSnapshotWriter
from transport_matters.storage.disk import DiskStorageBackend
from transport_matters.storage.disk_layout import DiskStorageLayout

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class FakeTailer:
    def __init__(self) -> None:
        self.unregistered: list[str] = []

    def unregister(self, session_id: str) -> None:
        self.unregistered.append(session_id)


@pytest.mark.asyncio
async def test_register_binding_maps_transcript_snapshot_and_unregisters_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tailer = FakeTailer()
    core = SharedProxyCore(
        capture=CaptureRuntime(
            http_client=cast("Any", None),
            token_counter=cast("Any", None),
            index_tailer=cast("Any", tailer),
        ),
        snapshots=SharedTranscriptSnapshotWriter(),
    )
    binding = ProxyRunBinding(
        run_id="run-1",
        cli="claude",
        working_dir=tmp_path,
        storage=DiskStorageBackend(tmp_path / "run-1"),
        listen_port=19001,
        upstream="https://api.anthropic.com",
        agent_home_dir=tmp_path / "home",
        owned_native_session_id="native-1",
        owned_source_descriptor="claude:owned",
    )

    async def fake_register_owned_cursor(
        received_tailer: object,
        received_binding: ProxyRunBinding,
        started_at: str,
        *,
        on_session_bound: Callable[[SessionBinding], None],
    ) -> None:
        assert received_tailer is tailer
        assert received_binding is binding
        assert started_at
        on_session_bound(
            SessionBinding(
                session_id="session-1",
                provider="anthropic",
                run_id="run-1",
                cwd=str(tmp_path),
                workspace_slug="workspace",
                workspace_hash="hash",
                started_at=started_at,
                cli="claude",
                native_session_id="native-1",
            )
        )

    monkeypatch.setattr(
        "transport_matters.shared_proxy.core.register_owned_cursor",
        fake_register_owned_cursor,
    )

    await core.register_binding(binding)
    core.snapshots("session-1", 0, b'{"type":"session_meta"}\n')

    path = DiskStorageLayout(tmp_path / "run-1").transcript_snapshot_path("session-1")
    assert path.read_bytes() == b'{"type":"session_meta"}\n'

    core.unregister_binding(binding)
    assert tailer.unregistered == ["session-1"]


def test_shared_snapshot_writer_captures_child_cursor_and_advances(
    tmp_path: Path,
) -> None:
    snapshots = SharedTranscriptSnapshotWriter()
    storage_root = tmp_path / "run-1"
    snapshots.register_run("run-1", storage_root)
    tailer = TranscriptTailer(
        snapshot=snapshots,
        on_cursor_registered=snapshots.register_cursor,
    )
    child_path = tmp_path / "child.jsonl"
    child_bytes = b"not-json\n"
    child_path.write_bytes(child_bytes)
    cursor = TailCursor(
        binding=SessionBinding(
            session_id="child-session",
            provider="anthropic",
            run_id="run-1",
            cwd=str(tmp_path),
            workspace_slug="workspace",
            workspace_hash="hash",
            started_at="2026-06-17T00:00:00+00:00",
            cli="claude",
            native_session_id="child-native",
            parent_session_id="session-1",
        ),
        source=FileTailSource(path=str(child_path), format="claude_jsonl"),
        adapter=cast("Any", None),
    )

    tailer.register(cursor)
    tailer.poll()

    assert cursor.byte_offset == len(child_bytes)
    path = DiskStorageLayout(storage_root).transcript_snapshot_path("child-session")
    assert path.read_bytes() == child_bytes
