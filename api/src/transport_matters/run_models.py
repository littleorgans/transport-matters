from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol

from transport_matters.captured_run import WEB_RUNTIME_EXTERNAL
from transport_matters.pty_session import (
    DEFAULT_TERMINAL_COLS,
    DEFAULT_TERMINAL_ROWS,
)
from transport_matters.space.models import ResolvedWorktree, SpaceId, WorktreeId

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from importlib.resources.abc import Traversable
    from pathlib import Path

    from transport_matters.captured_run import (
        CapturedRunHarness,
        CapturedRunRequest,
        CapturedRunSpawnSpec,
        CapturedRunWebRuntime,
    )
    from transport_matters.osc_color_responder import OscColorResponder
    from transport_matters.pty_session import TerminalPty
    from transport_matters.run_terminal import ScrollbackRing, TerminalAttachment, TerminalFanout
    from transport_matters.runtime_templates import RuntimeTemplateRef

TerminateReason = Literal["explicit", "shutdown", "idle-timeout", "deploy-restart"]
RunEndReason = TerminateReason | Literal["natural-exit", "failed"]
RunManagerErrorCode = Literal[
    "bind_conflict",
    "invalid_cwd",
    "launch_failed",
    "proxy_start_timeout",
    "run_manager_closed",
    "run_not_attachable",
    "run_stale",
    "run_terminated",
    "session_store_unavailable",
    "unsupported_harness",
]


class PrepareCapturedRun(Protocol):
    def __call__(
        self,
        request: CapturedRunRequest,
        *,
        require_addon: Callable[[], Traversable],
        resolve_mitmdump: Callable[[], str | None],
        which: Callable[..., str | None],
        port_in_use: Callable[[int], bool],
        allocate_port_pair: Callable[[], tuple[int, int]],
        inject_system_prompt: Callable[..., list[str]],
        user_supplied_system_prompt: Callable[[list[str]], bool],
        install_signal_handlers: bool = False,
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLeaseHandle]: ...


class CapturedRunLeaseHandle(Protocol):
    def close(self) -> None: ...


class RunState(StrEnum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"
    EXITED = "EXITED"
    FAILED = "FAILED"


class RunManagerError(RuntimeError):
    def __init__(self, code: RunManagerErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RunNotFoundError(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class SpawnRun:
    harness: CapturedRunHarness
    resolved_worktree: ResolvedWorktree
    cols: int = DEFAULT_TERMINAL_COLS
    rows: int = DEFAULT_TERMINAL_ROWS
    passthrough: tuple[str, ...] = ()
    proxy_port: int | None = None
    web_port: int | None = None
    upstream: str | None = None
    storage_dir: Path | None = None
    home_dir: Path | None = None
    client_bin: Path | None = None
    client_disabled: bool = False
    no_system_prompt: bool = False
    debug: bool = False
    web_runtime: CapturedRunWebRuntime = WEB_RUNTIME_EXTERNAL
    default_client_passthrough: tuple[str, ...] = ()
    runtime_template: RuntimeTemplateRef | None = None
    launch_fields: dict[str, object] = field(default_factory=dict)
    idempotency_key: str | None = None
    start_on_attach: bool = False
    defer_session_ownership: bool = False
    bypass_permissions: bool = False
    # Bridge answers the harness OSC 10/11 color queries.
    osc_color_replies: bool = True


@dataclass(frozen=True, slots=True)
class RunFilters:
    harness: CapturedRunHarness | None = None
    cwd: Path | None = None
    space_id: SpaceId | None = None
    worktree_id: WorktreeId | None = None
    states: frozenset[RunState] | None = None


@dataclass(frozen=True, slots=True)
class ManagedRunView:
    run_id: str
    harness: CapturedRunHarness
    cwd: Path
    space_id: SpaceId
    worktree_id: WorktreeId
    storage_dir: Path
    proxy_port: int
    web_port: int | None
    native_session_id: str | None
    state: RunState
    created_at: datetime
    started_at: datetime
    updated_at: datetime
    viewer_count: int
    viewerless_since: datetime | None
    exit_code: int | None
    end_reason: str | None
    error: str | None
    scrollback_bytes: int
    scrollback_limit_bytes: int


@dataclass(slots=True)
class ManagedRun:
    run_id: str
    harness: CapturedRunHarness
    cwd: Path
    space_id: SpaceId
    worktree_id: WorktreeId
    state: RunState
    spawn_spec: CapturedRunSpawnSpec
    lease: CapturedRunLeaseHandle
    terminal: TerminalPty | None
    terminal_output: TerminalFanout
    created_at: datetime
    started_at: datetime
    updated_at: datetime
    viewerless_since: datetime | None
    exit_code: int | None
    end_reason: str | None
    error: str | None
    # None when the bridge should stay silent.
    osc_responder: OscColorResponder | None
    start_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    drain_task: asyncio.Task[None] | None = None

    @property
    def scrollback(self) -> ScrollbackRing:
        return self.terminal_output.scrollback

    @property
    def attachments(self) -> dict[str, TerminalAttachment]:
        return self.terminal_output.attachments

    def view(self) -> ManagedRunView:
        return ManagedRunView(
            run_id=self.run_id,
            harness=self.harness,
            cwd=self.cwd,
            space_id=self.space_id,
            worktree_id=self.worktree_id,
            storage_dir=self.spawn_spec.storage_dir,
            proxy_port=self.spawn_spec.proxy_port,
            web_port=self.spawn_spec.web_port,
            native_session_id=(
                self.spawn_spec.managed_session.native_session_id
                if self.spawn_spec.managed_session is not None
                else None
            ),
            state=self.state,
            created_at=self.created_at,
            started_at=self.started_at,
            updated_at=self.updated_at,
            viewer_count=len(self.attachments),
            viewerless_since=self.viewerless_since,
            exit_code=self.exit_code,
            end_reason=self.end_reason,
            error=self.error,
            scrollback_bytes=self.scrollback.total_bytes,
            scrollback_limit_bytes=self.scrollback.max_bytes,
        )
