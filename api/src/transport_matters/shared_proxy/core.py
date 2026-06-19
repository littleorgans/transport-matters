"""Shared proxy capture core.

The shared mitmproxy subprocess has one capture core and many run bindings.
This module owns the shared transcript tailer registration that is specific to
Context B.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from transport_matters.addon_runtime import (
    CaptureRuntime,
    close_capture_runtime,
    load_shared_capture_runtime,
    register_owned_cursor,
)
from transport_matters.shared_proxy.binding import ProxyRunBinding, require_run_id
from transport_matters.shared_proxy.control import SharedProxyControlError
from transport_matters.storage.transcript_snapshot import make_transcript_snapshot_writer

if TYPE_CHECKING:
    from _thread import LockType
    from collections.abc import Callable

    from transport_matters.counting import TokenCountingClient
    from transport_matters.index.adapters.base import SessionBinding
    from transport_matters.index.tailer import TailCursor


@dataclass(slots=True)
class SharedTranscriptSnapshotWriter:
    """Route tailer snapshot writes to the owning run's tier 1 storage root."""

    _writers_by_run_id: dict[str, Callable[[str, int, bytes], None]] = field(default_factory=dict)
    _run_id_by_session: dict[str, str] = field(default_factory=dict)
    _lock: LockType = field(default_factory=Lock, init=False, repr=False)

    def register_run(self, run_id: str, storage_root: Path) -> None:
        writer = make_transcript_snapshot_writer(storage_root)
        with self._lock:
            self._writers_by_run_id[run_id] = writer

    def register_session(self, binding: SessionBinding) -> None:
        run_id = binding.run_id
        with self._lock:
            if run_id in self._writers_by_run_id:
                self._run_id_by_session[binding.session_id] = run_id

    def register_cursor(self, cursor: TailCursor) -> None:
        self.register_session(cursor.binding)

    def unregister(self, run_id: str) -> tuple[str, ...]:
        with self._lock:
            self._writers_by_run_id.pop(run_id, None)
            sessions = tuple(
                session_id
                for session_id, mapped_run_id in list(self._run_id_by_session.items())
                if mapped_run_id == run_id
            )
            for session_id in sessions:
                self._run_id_by_session.pop(session_id, None)
            return sessions

    def __call__(self, session_id: str, start_offset: int, consumed: bytes) -> None:
        with self._lock:
            run_id = self._run_id_by_session.get(session_id)
            writer = self._writers_by_run_id.get(run_id) if run_id is not None else None
        if writer is None:
            msg = f"no transcript snapshot writer registered for session {session_id!r}"
            raise RuntimeError(msg)
        writer(session_id, start_offset, consumed)


class SharedProxyCore:
    """Shared subprocess runtime for capture, counting, and transcript tailing."""

    def __init__(
        self,
        *,
        capture: CaptureRuntime,
        snapshots: SharedTranscriptSnapshotWriter,
        bindings_by_run_id: dict[str, ProxyRunBinding] | None = None,
    ) -> None:
        self.capture = capture
        self.snapshots = snapshots
        self._bindings_by_run_id = bindings_by_run_id if bindings_by_run_id is not None else {}

    @property
    def token_counter(self) -> TokenCountingClient:
        return self.capture.token_counter

    async def register_binding(self, binding: ProxyRunBinding) -> None:
        run_id = require_run_id(binding.run_id)
        tailer = self.capture.index_tailer
        if tailer is None:
            msg = "shared proxy session capture is unavailable"
            raise SharedProxyControlError("session_capture_unavailable", msg)
        storage_root = _storage_root(binding)
        started_at = datetime.now(UTC).isoformat()

        def bind_snapshot_writer(session_binding: SessionBinding) -> None:
            self.snapshots.register_session(session_binding)

        try:
            self.snapshots.register_run(run_id, storage_root)
            self._bindings_by_run_id[run_id] = binding
            if binding.owned_native_session_id is None or binding.owned_source_descriptor is None:
                return
            await register_owned_cursor(
                tailer,
                binding,
                started_at,
                on_session_bound=bind_snapshot_writer,
            )
        except Exception as exc:
            self._bindings_by_run_id.pop(run_id, None)
            self.snapshots.unregister(run_id)
            msg = f"owned transcript cursor registration failed for run {run_id!r}"
            raise SharedProxyControlError("owned_cursor_registration_failed", msg) from exc

    def unregister_binding(self, binding: ProxyRunBinding) -> None:
        run_id = require_run_id(binding.run_id)
        self._bindings_by_run_id.pop(run_id, None)
        session_ids = self.snapshots.unregister(run_id)
        if self.capture.index_tailer is not None:
            for session_id in session_ids:
                self.capture.index_tailer.unregister(session_id)

    async def close(self) -> None:
        await close_capture_runtime(self.capture)


def load_shared_proxy_core() -> SharedProxyCore:
    snapshots = SharedTranscriptSnapshotWriter()
    bindings_by_run_id: dict[str, ProxyRunBinding] = {}
    capture = load_shared_capture_runtime(
        snapshot_writer=snapshots,
        on_cursor_registered=snapshots.register_cursor,
        binding_for_run_id=bindings_by_run_id.get,
    )
    return SharedProxyCore(
        capture=capture,
        snapshots=snapshots,
        bindings_by_run_id=bindings_by_run_id,
    )


def _storage_root(binding: ProxyRunBinding) -> Path:
    root = getattr(binding.storage, "root", None)
    if isinstance(root, Path):
        return root
    msg = f"shared proxy binding {binding.run_id!r} storage has no disk root"
    raise SharedProxyControlError("missing_storage_root", msg)
