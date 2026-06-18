from __future__ import annotations

import threading
import time
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
    from collections.abc import Callable, Iterator
    from pathlib import Path


class FakeTailer:
    def __init__(self) -> None:
        self.unregistered: list[str] = []

    def unregister(self, session_id: str) -> None:
        self.unregistered.append(session_id)


class SlowItemsDict(dict[str, str]):
    def __init__(
        self,
        values: dict[str, str],
        *,
        entered: threading.Event,
        unblock: threading.Event,
    ) -> None:
        super().__init__(values)
        self.entered = entered
        self.unblock = unblock

    def items(self) -> Iterator[tuple[str, str]]:  # type: ignore[override]
        iterator = super().items()
        for item in iterator:
            self.entered.set()
            assert self.unblock.wait(timeout=1)
            yield item


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
        harness="claude",
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
                harness="claude",
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
    cursor = _child_cursor(tmp_path, session_id="child-session", source_path=child_path)

    tailer.register(cursor)
    tailer.poll()

    assert cursor.byte_offset == len(child_bytes)
    path = DiskStorageLayout(storage_root).transcript_snapshot_path("child-session")
    assert path.read_bytes() == child_bytes


def test_shared_snapshot_writer_unregister_races_child_cursor_registration(
    tmp_path: Path,
) -> None:
    snapshots = SharedTranscriptSnapshotWriter()
    snapshots.register_run("run-1", tmp_path / "run-1")
    entered_iteration = threading.Event()
    unblock_iteration = threading.Event()
    snapshots._run_id_by_session = SlowItemsDict(
        {"existing-child-1": "run-1", "existing-child-2": "run-1"},
        entered=entered_iteration,
        unblock=unblock_iteration,
    )
    errors: list[BaseException] = []
    removed: list[str] = []

    def unregister_run() -> None:
        try:
            removed.extend(snapshots.unregister("run-1"))
        except BaseException as exc:
            errors.append(exc)

    def register_child() -> None:
        try:
            snapshots.register_cursor(_child_cursor(tmp_path, session_id="racing-child"))
        except BaseException as exc:
            errors.append(exc)

    unregister_thread = threading.Thread(target=unregister_run)
    register_thread = threading.Thread(target=register_child)

    unregister_thread.start()
    assert entered_iteration.wait(timeout=1)
    register_thread.start()
    time.sleep(0.02)
    unblock_iteration.set()
    unregister_thread.join(timeout=1)
    register_thread.join(timeout=1)

    assert not unregister_thread.is_alive()
    assert not register_thread.is_alive()
    assert errors == []
    assert sorted(removed) == ["existing-child-1", "existing-child-2"]
    assert snapshots._run_id_by_session == {}
    with pytest.raises(RuntimeError, match="racing-child"):
        snapshots("racing-child", 0, b"not-json\n")


def _child_cursor(
    tmp_path: Path,
    *,
    session_id: str,
    source_path: Path | None = None,
) -> TailCursor:
    return TailCursor(
        binding=SessionBinding(
            session_id=session_id,
            provider="anthropic",
            run_id="run-1",
            cwd=str(tmp_path),
            workspace_slug="workspace",
            workspace_hash="hash",
            started_at="2026-06-17T00:00:00+00:00",
            harness="claude",
            native_session_id=f"{session_id}-native",
            parent_session_id="session-1",
        ),
        source=FileTailSource(
            path=str(source_path or tmp_path / f"{session_id}.jsonl"),
            format="claude_jsonl",
        ),
        adapter=cast("Any", None),
    )
