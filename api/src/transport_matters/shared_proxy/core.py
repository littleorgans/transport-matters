"""Shared proxy capture core.

The shared mitmproxy subprocess has one capture core and many run bindings.
This module owns the shared transcript tailer registration that is specific to
Context B.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
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
    from collections.abc import Callable

    from transport_matters.counting import TokenCountingClient
    from transport_matters.index.adapters.base import SessionBinding


@dataclass(slots=True)
class SharedTranscriptSnapshotWriter:
    """Route tailer snapshot writes to the owning run's tier 1 storage root."""

    _writers: dict[str, Callable[[str, int, bytes], None]] = field(default_factory=dict)
    _session_by_run_id: dict[str, str] = field(default_factory=dict)

    def register(self, run_id: str, session_id: str, storage_root: Path) -> None:
        self._writers[session_id] = make_transcript_snapshot_writer(storage_root)
        self._session_by_run_id[run_id] = session_id

    def unregister(self, run_id: str) -> str | None:
        session_id = self._session_by_run_id.pop(run_id, None)
        if session_id is not None:
            self._writers.pop(session_id, None)
        return session_id

    def __call__(self, session_id: str, start_offset: int, consumed: bytes) -> None:
        writer = self._writers.get(session_id)
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
    ) -> None:
        self.capture = capture
        self.snapshots = snapshots

    @property
    def token_counter(self) -> TokenCountingClient:
        return self.capture.token_counter

    async def register_binding(self, binding: ProxyRunBinding) -> None:
        run_id = require_run_id(binding.run_id)
        if binding.owned_native_session_id is None or binding.owned_source_descriptor is None:
            return
        tailer = self.capture.index_tailer
        if tailer is None:
            msg = "shared proxy session capture is unavailable"
            raise SharedProxyControlError("session_capture_unavailable", msg)
        storage_root = _storage_root(binding)
        started_at = datetime.now(UTC).isoformat()

        def bind_snapshot_writer(session_binding: SessionBinding) -> None:
            self.snapshots.register(run_id, session_binding.session_id, storage_root)

        try:
            await register_owned_cursor(
                tailer,
                binding,
                started_at,
                on_session_bound=bind_snapshot_writer,
            )
        except Exception as exc:
            self.snapshots.unregister(run_id)
            msg = f"owned transcript cursor registration failed for run {run_id!r}"
            raise SharedProxyControlError("owned_cursor_registration_failed", msg) from exc

    def unregister_binding(self, binding: ProxyRunBinding) -> None:
        run_id = require_run_id(binding.run_id)
        session_id = self.snapshots.unregister(run_id)
        if session_id is not None and self.capture.index_tailer is not None:
            self.capture.index_tailer.unregister(session_id)

    async def close(self) -> None:
        await close_capture_runtime(self.capture)


def load_shared_proxy_core() -> SharedProxyCore:
    snapshots = SharedTranscriptSnapshotWriter()
    capture = load_shared_capture_runtime(snapshot_writer=snapshots)
    return SharedProxyCore(capture=capture, snapshots=snapshots)


def _storage_root(binding: ProxyRunBinding) -> Path:
    root = getattr(binding.storage, "root", None)
    if isinstance(root, Path):
        return root
    msg = f"shared proxy binding {binding.run_id!r} storage has no disk root"
    raise SharedProxyControlError("missing_storage_root", msg)
