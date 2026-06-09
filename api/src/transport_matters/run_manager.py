from __future__ import annotations

import asyncio
import contextlib
import errno
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol
from uuid import uuid4

from transport_matters.captured_run import (
    CLAUDE_CLIENT_NAME,
    CLAUDE_UPSTREAM_DEFAULT,
    CODEX_CLIENT_NAME,
    WEB_RUNTIME_EXTERNAL,
    CapturedRunBindConflict,
    CapturedRunDependencies,
    CapturedRunLease,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
    CapturedRunWebRuntime,
    default_claude_run_dependencies,
    prepare_captured_run,
)
from transport_matters.pty_session import (
    TerminalPty,
    close_terminal_master,
    spawn_pty_process,
    terminate_terminal_pty,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

logger = logging.getLogger(__name__)

CapturedRunCli = Literal["claude", "codex"]
StopReason = Literal["explicit-stop", "shutdown", "idle-timeout", "natural-exit", "failed"]

DEFAULT_SCROLLBACK_BYTES = 2 * 1024 * 1024
DEFAULT_TERMINAL_COLS = 80
DEFAULT_TERMINAL_ROWS = 24
DEFAULT_ATTACHMENT_QUEUE_SIZE = 256
PTY_READ_CHUNK_SIZE = 8192
SLOW_VIEWER_CLOSE_CODE = "retryable-overload"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PrepareCapturedRun(Protocol):
    def __call__(
        self,
        request: CapturedRunRequest,
        *,
        require_addon: Callable[[], Any],
        resolve_mitmdump: Callable[[], str | None],
        which: Callable[..., str | None],
        port_in_use: Callable[[int], bool],
        allocate_port_pair: Callable[[], tuple[int, int]],
        inject_system_prompt: Callable[..., list[str]],
        user_supplied_system_prompt: Callable[[list[str]], bool],
        install_signal_handlers: bool = False,
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]: ...


class SpawnPtyProcess(Protocol):
    def __call__(
        self,
        *,
        argv: Sequence[str],
        env: Mapping[str, str],
        cwd: Path,
        cols: int,
        rows: int,
    ) -> TerminalPty: ...


class RunState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    EXITED = "exited"
    FAILED = "failed"


class RunManagerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RunNotFoundError(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class PtyChunk:
    seq: int
    data: bytes
    emitted_at: datetime


@dataclass(frozen=True, slots=True)
class AttachmentClosed:
    code: str
    retryable: bool
    message: str


TerminalQueueItem = PtyChunk | AttachmentClosed


class ScrollbackRing:
    def __init__(
        self,
        *,
        max_bytes: int = DEFAULT_SCROLLBACK_BYTES,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if max_bytes < 0:
            raise ValueError("scrollback max_bytes must be non negative")
        self._max_bytes = max_bytes
        self._clock = clock
        self._chunks: deque[PtyChunk] = deque()
        self._total_bytes = 0
        self._next_seq = 0

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def total_bytes(self) -> int:
        return self._total_bytes

    @property
    def next_seq(self) -> int:
        return self._next_seq

    def append(self, data: bytes, *, emitted_at: datetime | None = None) -> PtyChunk:
        emitted = emitted_at or self._clock()
        seq = self._next_seq
        self._next_seq += 1
        live_chunk = PtyChunk(seq=seq, data=data, emitted_at=emitted)
        if self._max_bytes == 0:
            return live_chunk

        stored_data = data[-self._max_bytes :] if len(data) > self._max_bytes else data
        if stored_data:
            stored_chunk = PtyChunk(seq=seq, data=stored_data, emitted_at=emitted)
            self._chunks.append(stored_chunk)
            self._total_bytes += len(stored_data)
            self._trim()
        return live_chunk

    def snapshot(self) -> tuple[PtyChunk, ...]:
        return tuple(self._chunks)

    def _trim(self) -> None:
        while self._total_bytes > self._max_bytes and self._chunks:
            chunk = self._chunks.popleft()
            self._total_bytes -= len(chunk.data)


@dataclass(slots=True)
class TerminalAttachment:
    attachment_id: str
    queue: asyncio.Queue[TerminalQueueItem]
    cols: int
    rows: int
    connected_at: datetime
    closed_reason: str | None = None


@dataclass(frozen=True, slots=True)
class AttachedTerminal:
    attachment: TerminalAttachment
    scrollback: tuple[PtyChunk, ...]
    start_seq: int


@dataclass(frozen=True, slots=True)
class SpawnRun:
    cli: CapturedRunCli
    cwd: Path | None = None
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


@dataclass(frozen=True, slots=True)
class RunFilters:
    cli: CapturedRunCli | None = None
    states: frozenset[RunState] | None = None


@dataclass(frozen=True, slots=True)
class ManagedRunView:
    run_id: str
    cli: CapturedRunCli
    cwd: Path
    state: RunState
    created_at: datetime
    started_at: datetime
    updated_at: datetime
    viewer_count: int
    viewerless_since: datetime | None
    exit_code: int | None
    stop_reason: str | None


@dataclass(slots=True)
class ManagedRun:
    run_id: str
    cli: CapturedRunCli
    cwd: Path
    state: RunState
    spawn_spec: CapturedRunSpawnSpec
    lease: CapturedRunLease
    terminal: TerminalPty
    scrollback: ScrollbackRing
    attachments: dict[str, TerminalAttachment]
    created_at: datetime
    started_at: datetime
    updated_at: datetime
    viewerless_since: datetime | None
    exit_code: int | None
    stop_reason: str | None
    drain_task: asyncio.Task[None] = field(init=False)

    def view(self) -> ManagedRunView:
        return ManagedRunView(
            run_id=self.run_id,
            cli=self.cli,
            cwd=self.cwd,
            state=self.state,
            created_at=self.created_at,
            started_at=self.started_at,
            updated_at=self.updated_at,
            viewer_count=len(self.attachments),
            viewerless_since=self.viewerless_since,
            exit_code=self.exit_code,
            stop_reason=self.stop_reason,
        )


class RunManager:
    def __init__(
        self,
        *,
        dependencies: CapturedRunDependencies | None = None,
        prepare_run: PrepareCapturedRun = prepare_captured_run,
        spawn_pty: SpawnPtyProcess = spawn_pty_process,
        clock: Callable[[], datetime] = _utcnow,
        scrollback_bytes: int = DEFAULT_SCROLLBACK_BYTES,
        attachment_queue_size: int = DEFAULT_ATTACHMENT_QUEUE_SIZE,
        read_chunk_size: int = PTY_READ_CHUNK_SIZE,
        install_signal_handlers: bool = False,
    ) -> None:
        self._dependencies = dependencies or default_claude_run_dependencies()
        self._prepare_run = prepare_run
        self._spawn_pty = spawn_pty
        self._clock = clock
        self._scrollback_bytes = scrollback_bytes
        self._attachment_queue_size = attachment_queue_size
        self._read_chunk_size = read_chunk_size
        self._install_signal_handlers = install_signal_handlers
        self._runs: dict[str, ManagedRun] = {}
        self._teardown_lock = asyncio.Lock()
        self._closed = False

    async def spawn(self, request: SpawnRun) -> ManagedRun:
        if self._closed:
            raise RunManagerError("run_manager_closed", "run manager is closed")

        spawn_spec, lease = await self._prepare_request(request)
        terminal: TerminalPty | None = None
        drain_task: asyncio.Task[None] | None = None
        registered_run_id: str | None = None
        try:
            client = spawn_spec.client
            if client is None:
                raise RunManagerError(
                    "launch_failed",
                    f"captured {request.cli} launch did not produce a client process",
                )

            terminal = await asyncio.to_thread(
                self._spawn_pty,
                argv=client.argv,
                env=client.env,
                cwd=client.cwd,
                cols=request.cols,
                rows=request.rows,
            )
            now = self._clock()
            run = ManagedRun(
                run_id=spawn_spec.run_id,
                cli=request.cli,
                cwd=spawn_spec.working_dir,
                state=RunState.STARTING,
                spawn_spec=spawn_spec,
                lease=lease,
                terminal=terminal,
                scrollback=ScrollbackRing(max_bytes=self._scrollback_bytes, clock=self._clock),
                attachments={},
                created_at=now,
                started_at=now,
                updated_at=now,
                viewerless_since=now,
                exit_code=None,
                stop_reason=None,
            )
            if self._closed:
                raise RunManagerError("run_manager_closed", "run manager is closed")

            self._runs[run.run_id] = run
            registered_run_id = run.run_id
            drain_task = asyncio.create_task(
                self._drain_run(run), name=f"transport-run-drain:{run.run_id}"
            )
            run.drain_task = drain_task
            run.state = RunState.RUNNING
            run.updated_at = self._clock()
            return run
        except Exception as exc:
            if registered_run_id is not None:
                self._runs.pop(registered_run_id, None)
            await self._rollback_post_prepare(
                terminal=terminal,
                drain_task=drain_task,
                lease=lease,
            )
            if isinstance(exc, RunManagerError):
                raise
            raise RunManagerError("launch_failed", str(exc)) from exc

    def get(self, run_id: str) -> ManagedRun:
        run = self._runs.get(run_id)
        if run is None:
            raise RunNotFoundError(run_id)
        return run

    def list(self, filters: RunFilters | None = None) -> list[ManagedRunView]:
        runs = tuple(self._runs.values())
        if filters is not None:
            if filters.cli is not None:
                runs = tuple(run for run in runs if run.cli == filters.cli)
            if filters.states is not None:
                runs = tuple(run for run in runs if run.state in filters.states)
        return [run.view() for run in runs]

    def attach(
        self,
        run_id: str,
        *,
        cols: int,
        rows: int,
        attachment_id: str | None = None,
        queue_maxsize: int | None = None,
    ) -> AttachedTerminal:
        run = self.get(run_id)
        if run.state is not RunState.RUNNING:
            raise RunManagerError("run_not_attachable", f"run {run_id} is {run.state}")
        scrollback = run.scrollback.snapshot()
        start_seq = run.scrollback.next_seq
        attachment = TerminalAttachment(
            attachment_id=attachment_id or uuid4().hex,
            queue=asyncio.Queue(maxsize=queue_maxsize or self._attachment_queue_size),
            cols=cols,
            rows=rows,
            connected_at=self._clock(),
        )
        run.attachments[attachment.attachment_id] = attachment
        run.viewerless_since = None
        run.updated_at = self._clock()
        return AttachedTerminal(
            attachment=attachment,
            scrollback=scrollback,
            start_seq=start_seq,
        )

    def detach(self, run_id: str, attachment_id: str) -> None:
        run = self.get(run_id)
        self._detach(run, attachment_id)

    async def stop(self, run_id: str, *, reason: StopReason = "explicit-stop") -> ManagedRunView:
        run = self.get(run_id)
        await self._teardown_run(run, terminate=True, reason=reason)
        return run.view()

    async def close(self) -> None:
        self._closed = True
        runs = [run for run in self._runs.values() if run.state not in _TERMINAL_STATES]
        for run in runs:
            await self._teardown_run(run, terminate=True, reason="shutdown")

    async def _prepare_request(
        self, request: SpawnRun
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
        captured_request = self._captured_request(request)
        try:
            return await asyncio.to_thread(
                self._prepare_run,
                captured_request,
                require_addon=self._dependencies.require_addon,
                resolve_mitmdump=self._dependencies.resolve_mitmdump,
                which=self._dependencies.which,
                port_in_use=self._dependencies.port_in_use,
                allocate_port_pair=self._dependencies.allocate_port_pair,
                inject_system_prompt=self._dependencies.inject_system_prompt,
                user_supplied_system_prompt=self._dependencies.user_supplied_system_prompt,
                install_signal_handlers=self._install_signal_handlers,
            )
        except CapturedRunBindConflict as exc:
            raise RunManagerError("bind_conflict", str(exc)) from exc
        except RunManagerError:
            raise
        except Exception as exc:
            raise RunManagerError("launch_failed", str(exc)) from exc

    def _captured_request(self, request: SpawnRun) -> CapturedRunRequest:
        if request.cli not in _VALID_CAPTURED_RUN_CLIS:
            raise RunManagerError("launch_failed", f"unsupported captured run cli: {request.cli}")

        store_error = self._dependencies.check_session_store()
        if store_error is not None:
            raise RunManagerError("session_store_unavailable", store_error)

        cwd = self._resolve_cwd(request.cwd)
        upstream = request.upstream
        if upstream is None:
            upstream = CLAUDE_UPSTREAM_DEFAULT if request.cli == CLAUDE_CLIENT_NAME else ""
        return CapturedRunRequest(
            client_name=request.cli,
            passthrough=request.passthrough,
            directory=cwd,
            proxy_port=request.proxy_port,
            web_port=request.web_port,
            upstream=upstream,
            storage_dir=request.storage_dir,
            home_dir=request.home_dir,
            client_bin=request.client_bin,
            client_disabled=request.client_disabled,
            no_system_prompt=request.no_system_prompt,
            debug=request.debug,
            web_runtime=request.web_runtime,
            default_client_passthrough=request.default_client_passthrough,
        )

    def _resolve_cwd(self, cwd: Path | None) -> Path:
        working_dir = Path.cwd() if cwd is None else cwd.expanduser()
        if not working_dir.is_absolute():
            raise RunManagerError("launch_failed", "cwd must be an absolute path")
        if not working_dir.exists():
            raise RunManagerError("launch_failed", f"cwd does not exist: {working_dir}")
        if not working_dir.is_dir():
            raise RunManagerError("launch_failed", f"cwd is not a directory: {working_dir}")
        return working_dir.resolve()

    async def _drain_run(self, run: ManagedRun) -> None:
        loop = asyncio.get_running_loop()
        done: asyncio.Future[None] = loop.create_future()
        fd = run.terminal.master_fd
        loop.add_reader(fd, self._handle_pty_readable, run, done)
        failure: BaseException | None = None
        try:
            await done
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = exc
        finally:
            self._remove_reader(fd)

        if failure is None:
            await self._teardown_run(run, terminate=False, reason="natural-exit")
            return

        logger.error(
            "managed run drain failed",
            exc_info=(type(failure), failure, failure.__traceback__),
        )
        await self._teardown_run(run, terminate=False, reason="failed", failure=failure)

    def _handle_pty_readable(self, run: ManagedRun, done: asyncio.Future[None]) -> None:
        if done.done():
            return
        try:
            data = os.read(run.terminal.master_fd, self._read_chunk_size)
        except OSError as exc:
            if exc.errno in {errno.EIO, errno.EBADF}:
                done.set_result(None)
                return
            done.set_exception(exc)
            return
        if not data:
            done.set_result(None)
            return

        now = self._clock()
        if run.state not in {RunState.RUNNING, RunState.STOPPING}:
            return
        chunk = run.scrollback.append(data, emitted_at=now)
        run.updated_at = now
        overloaded: list[str] = []
        for attachment in tuple(run.attachments.values()):
            try:
                attachment.queue.put_nowait(chunk)
            except asyncio.QueueFull:
                overloaded.append(attachment.attachment_id)
        for attachment_id in overloaded:
            self._close_attachment(
                run,
                attachment_id,
                code=SLOW_VIEWER_CLOSE_CODE,
                retryable=True,
                message="terminal output queue overloaded; reconnect to resume",
            )

    async def _teardown_run(
        self,
        run: ManagedRun,
        *,
        terminate: bool,
        reason: StopReason,
        failure: BaseException | None = None,
    ) -> None:
        async with self._teardown_lock:
            if run.state in _TERMINAL_STATES and run.terminal.closed:
                return

            run.state = RunState.STOPPING if terminate else RunState.EXITED
            if reason == "failed":
                run.state = RunState.FAILED
            run.stop_reason = str(failure) if failure is not None else reason
            run.updated_at = self._clock()
            self._close_all_attachments(
                run,
                code="run-ended",
                retryable=False,
                message=f"run ended: {run.stop_reason}",
            )

            current_task = asyncio.current_task()
            if run.drain_task is not current_task and not run.drain_task.done():
                run.drain_task.cancel()
                self._remove_reader(run.terminal.master_fd)
                with contextlib.suppress(asyncio.CancelledError):
                    await run.drain_task

            self._remove_reader(run.terminal.master_fd)
            if terminate:
                await asyncio.to_thread(terminate_terminal_pty, run.terminal)
            else:
                await asyncio.to_thread(close_terminal_master, run.terminal)
            await asyncio.to_thread(run.lease.close)

            run.exit_code = run.terminal.process.poll()
            if run.state is RunState.STOPPING:
                run.state = RunState.EXITED
            run.updated_at = self._clock()

    async def _rollback_post_prepare(
        self,
        *,
        terminal: TerminalPty | None,
        drain_task: asyncio.Task[None] | None,
        lease: CapturedRunLease,
    ) -> None:
        if drain_task is not None and not drain_task.done():
            drain_task.cancel()
            if terminal is not None:
                self._remove_reader(terminal.master_fd)
            with contextlib.suppress(asyncio.CancelledError):
                await drain_task
        if terminal is not None:
            self._remove_reader(terminal.master_fd)
            await asyncio.to_thread(terminate_terminal_pty, terminal)
        await asyncio.to_thread(lease.close)

    def _close_all_attachments(
        self,
        run: ManagedRun,
        *,
        code: str,
        retryable: bool,
        message: str,
    ) -> None:
        for attachment_id in tuple(run.attachments):
            self._close_attachment(
                run,
                attachment_id,
                code=code,
                retryable=retryable,
                message=message,
            )

    def _close_attachment(
        self,
        run: ManagedRun,
        attachment_id: str,
        *,
        code: str,
        retryable: bool,
        message: str,
    ) -> None:
        attachment = run.attachments.pop(attachment_id, None)
        if attachment is None:
            return
        attachment.closed_reason = code
        close_item = AttachmentClosed(code=code, retryable=retryable, message=message)
        with contextlib.suppress(asyncio.QueueFull):
            attachment.queue.put_nowait(close_item)
        if not run.attachments and run.state is RunState.RUNNING:
            run.viewerless_since = self._clock()

    def _detach(self, run: ManagedRun, attachment_id: str) -> None:
        run.attachments.pop(attachment_id, None)
        if not run.attachments and run.state is RunState.RUNNING:
            run.viewerless_since = self._clock()
        run.updated_at = self._clock()

    def _remove_reader(self, fd: int) -> None:
        with contextlib.suppress(RuntimeError, ValueError, OSError):
            asyncio.get_running_loop().remove_reader(fd)


_TERMINAL_STATES = frozenset({RunState.EXITED, RunState.FAILED})
_VALID_CAPTURED_RUN_CLIS = frozenset({CLAUDE_CLIENT_NAME, CODEX_CLIENT_NAME})
