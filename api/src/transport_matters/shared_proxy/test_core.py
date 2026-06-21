from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import TYPE_CHECKING, Any, cast

import pytest

from transport_matters.addon_runtime import CaptureRuntime
from transport_matters.index.adapters.base import (
    FileTailSource,
    SessionBinding,
    encode_source_descriptor,
)
from transport_matters.index.tailer import TailCursor, TranscriptTailer
from transport_matters.session.async_dao import AsyncSessionDao
from transport_matters.session.ingest import EventWrite, build_event, build_event_batch
from transport_matters.session.pool import async_connect, create_async_pool
from transport_matters.session.writer import SessionWriter
from transport_matters.shared_proxy.addon import _runtime_binding_from_payload
from transport_matters.shared_proxy.binding import ProxyRunBinding
from transport_matters.shared_proxy.control import SharedProxyControlError
from transport_matters.shared_proxy.core import SharedProxyCore, SharedTranscriptSnapshotWriter
from transport_matters.shared_proxy.models import (
    SharedProxyBindingPayload,
    binding_payload_from_binding,
)
from transport_matters.space.models import SpaceId, WorktreeId
from transport_matters.storage.disk import DiskStorageBackend
from transport_matters.storage.disk_layout import DiskStorageLayout

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from transport_matters.session.testing import TestDb


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


class SpySnapshotWriter(SharedTranscriptSnapshotWriter):
    __slots__ = ("calls",)

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def register_run(self, run_id: str, storage_root: Path) -> None:
        self.calls.append(f"register:{run_id}")
        super().register_run(run_id, storage_root)

    def unregister(self, run_id: str) -> tuple[str, ...]:
        self.calls.append(f"unregister:{run_id}")
        return super().unregister(run_id)


def _owned_binding(tmp_path: Path) -> ProxyRunBinding:
    return ProxyRunBinding(
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


def _capture_runtime(index_tailer: object | None) -> CaptureRuntime:
    return CaptureRuntime(
        http_client=cast("Any", None),
        token_counter=cast("Any", None),
        index_tailer=cast("Any", index_tailer),
    )


@pytest.mark.asyncio
async def test_shared_proxy_payload_round_trip_persists_space_identity(
    tmp_path: Path, test_db: TestDb
) -> None:
    native_session_id = "11111111-1111-4111-8111-111111111111"
    space_id = SpaceId.parse("22222222-2222-4222-8222-222222222222")
    worktree_id = WorktreeId.parse("33333333-3333-4333-8333-333333333333")
    transcript_path = tmp_path / "owned-claude.jsonl"
    transcript_path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "uuid": "turn-1",
                "parentUuid": None,
                "sessionId": native_session_id,
                "isSidechain": False,
                "timestamp": "2026-06-21T00:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "identity survived"}],
                },
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    descriptor = encode_source_descriptor(
        FileTailSource(path=str(transcript_path), format="claude_jsonl")
    )
    binding = ProxyRunBinding(
        run_id="run-identity",
        harness="claude",
        working_dir=tmp_path,
        storage=DiskStorageBackend(tmp_path / "run-identity"),
        listen_port=19001,
        upstream="https://api.anthropic.com",
        agent_home_dir=tmp_path / "home",
        owned_native_session_id=native_session_id,
        owned_source_descriptor=descriptor,
        space_id=space_id,
        worktree_id=worktree_id,
    )

    payload = binding_payload_from_binding(binding)
    round_tripped = SharedProxyBindingPayload.model_validate_json(
        payload.model_dump_json(by_alias=True)
    )
    runtime_binding = _runtime_binding_from_payload(round_tripped)

    assert runtime_binding.space_id == space_id
    assert runtime_binding.worktree_id == worktree_id

    loop = asyncio.get_running_loop()
    writer = SessionWriter(
        create_async_pool(test_db.database_url, min_size=1, max_size=1), loop=loop
    )

    def submit_batch(batch_binding: SessionBinding, events: list[EventWrite]) -> None:
        writer.submit_blocking(build_event_batch(batch_binding, events))

    tailer = TranscriptTailer(build_record=build_event, submit_batch=submit_batch)
    core = SharedProxyCore(
        capture=_capture_runtime(tailer),
        snapshots=SharedTranscriptSnapshotWriter(),
    )
    try:
        await core.register_binding(runtime_binding)
        await loop.run_in_executor(None, tailer.poll)

        async with await async_connect(test_db.database_url, autocommit=True) as conn:
            dao = AsyncSessionDao(conn)
            session = await dao.get_session(native_session_id)
            assert session is not None
            assert session.space_id == space_id
            assert session.worktree_id == worktree_id
    finally:
        await writer.aclose()


@pytest.mark.asyncio
async def test_register_binding_maps_transcript_snapshot_and_unregisters_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tailer = FakeTailer()
    core = SharedProxyCore(
        capture=_capture_runtime(tailer),
        snapshots=SharedTranscriptSnapshotWriter(),
    )
    binding = _owned_binding(tmp_path)

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


@pytest.mark.asyncio
async def test_register_owned_binding_requires_session_capture_and_cleans_up(
    tmp_path: Path,
) -> None:
    snapshots = SpySnapshotWriter()
    core = SharedProxyCore(
        capture=_capture_runtime(None),
        snapshots=snapshots,
    )
    binding = _owned_binding(tmp_path)

    with pytest.raises(SharedProxyControlError) as error:
        await core.register_binding(binding)

    assert error.value.code == "session_capture_unavailable"
    assert core._bindings_by_run_id == {}
    assert snapshots.calls == ["register:run-1", "unregister:run-1"]


@pytest.mark.asyncio
async def test_register_owned_binding_cursor_failure_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshots = SpySnapshotWriter()
    core = SharedProxyCore(
        capture=_capture_runtime(FakeTailer()),
        snapshots=snapshots,
    )
    binding = _owned_binding(tmp_path)

    async def fail_register_owned_cursor(*_: object, **__: object) -> None:
        raise RuntimeError("cursor boom")

    monkeypatch.setattr(
        "transport_matters.shared_proxy.core.register_owned_cursor",
        fail_register_owned_cursor,
    )

    with pytest.raises(SharedProxyControlError) as error:
        await core.register_binding(binding)

    assert error.value.code == "owned_cursor_registration_failed"
    assert core._bindings_by_run_id == {}
    assert snapshots.calls == ["register:run-1", "unregister:run-1"]


@pytest.mark.asyncio
async def test_register_deferred_binding_maps_run_for_late_cursor(tmp_path: Path) -> None:
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
        harness="codex",
        working_dir=tmp_path,
        storage=DiskStorageBackend(tmp_path / "run-1"),
        listen_port=19001,
        upstream="",
        agent_home_dir=tmp_path / "runtime-home",
        owned_native_session_id=None,
        owned_source_descriptor=None,
    )

    await core.register_binding(binding)
    core.snapshots.register_session(
        SessionBinding(
            session_id="session-1",
            provider="codex",
            run_id="run-1",
            cwd=str(tmp_path),
            workspace_slug="workspace",
            workspace_hash="hash",
            started_at="2026-06-19T00:00:00+00:00",
            harness="codex",
            native_session_id="native-1",
            home_dir=str(tmp_path / "runtime-home"),
        )
    )
    core.snapshots("session-1", 0, b'{"type":"session_meta"}\n')

    path = DiskStorageLayout(tmp_path / "run-1").transcript_snapshot_path("session-1")
    assert path.read_bytes() == b'{"type":"session_meta"}\n'

    core.unregister_binding(binding)
    assert tailer.unregistered == ["session-1"]


@pytest.mark.asyncio
async def test_register_deferred_binding_does_not_require_session_capture(
    tmp_path: Path,
) -> None:
    core = SharedProxyCore(
        capture=CaptureRuntime(
            http_client=cast("Any", None),
            token_counter=cast("Any", None),
            index_tailer=None,
        ),
        snapshots=SharedTranscriptSnapshotWriter(),
    )
    binding = ProxyRunBinding(
        run_id="run-1",
        harness="codex",
        working_dir=tmp_path,
        storage=DiskStorageBackend(tmp_path / "run-1"),
        listen_port=19001,
        upstream="",
        agent_home_dir=tmp_path / "runtime-home",
        owned_native_session_id=None,
        owned_source_descriptor=None,
    )

    await core.register_binding(binding)
    core.snapshots.register_session(
        SessionBinding(
            session_id="session-1",
            provider="codex",
            run_id="run-1",
            cwd=str(tmp_path),
            workspace_slug="workspace",
            workspace_hash="hash",
            started_at="2026-06-19T00:00:00+00:00",
            harness="codex",
            native_session_id="native-1",
            home_dir=str(tmp_path / "runtime-home"),
        )
    )
    core.snapshots("session-1", 0, b'{"type":"session_meta"}\n')

    path = DiskStorageLayout(tmp_path / "run-1").transcript_snapshot_path("session-1")
    assert path.read_bytes() == b'{"type":"session_meta"}\n'


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
