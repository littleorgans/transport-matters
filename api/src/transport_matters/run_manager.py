from __future__ import annotations

import asyncio
import contextlib
import errno
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from transport_matters.captured_run import (
    CLAUDE_CLIENT_NAME,
    CLAUDE_UPSTREAM_DEFAULT,
    CODEX_CLIENT_NAME,
    WEB_RUNTIME_EXTERNAL,
    CapturedRunBindConflict,
    CapturedRunCli,
    CapturedRunDependencies,
    CapturedRunProxyStartTimeout,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
    CapturedRunWebRuntime,
    default_claude_run_dependencies,
    prepare_captured_run,
)
from transport_matters.osc_color_responder import OscColorResponder
from transport_matters.pty_session import (
    DEFAULT_TERMINAL_COLS,
    DEFAULT_TERMINAL_ROWS,
    PTY_READ_CHUNK_SIZE,
    SpawnPtyProcess,
    TerminalPty,
    close_terminal_master,
    spawn_pty_process,
    terminate_terminal_pty,
    write_all,
)
from transport_matters.run_terminal import (
    DEFAULT_ATTACHMENT_QUEUE_SIZE,
    DEFAULT_SCROLLBACK_BYTES,
    AttachedTerminal,
    ScrollbackRing,
    TerminalAttachment,
    TerminalFanout,
)
from transport_matters.shared_proxy.run_preparation import prepare_shared_captured_run

if TYPE_CHECKING:
    from collections.abc import Callable

    from transport_matters.runtime_templates import RuntimeTemplateRef
    from transport_matters.shared_proxy.manager import SharedProxyManager

logger = logging.getLogger(__name__)

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
    "unsupported_cli",
]


def _utcnow() -> datetime:
    return datetime.now(UTC)


_SESSION_STORE_PREFLIGHT_CACHE_TTL = timedelta(seconds=3)


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
    runtime_template: RuntimeTemplateRef | None = None
    launch_fields: dict[str, object] = field(default_factory=dict)
    idempotency_key: str | None = None
    # Bridge answers the CLI's OSC 10/11 color queries (see osc_color_responder).
    osc_color_replies: bool = True


@dataclass(frozen=True, slots=True)
class _ValidatedSpawnRun:
    request: SpawnRun
    cwd: Path
    upstream: str


@dataclass(frozen=True, slots=True)
class RunFilters:
    cli: CapturedRunCli | None = None
    cwd: Path | None = None
    states: frozenset[RunState] | None = None


@dataclass(frozen=True, slots=True)
class ManagedRunView:
    run_id: str
    cli: CapturedRunCli
    cwd: Path
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
    cli: CapturedRunCli
    cwd: Path
    state: RunState
    spawn_spec: CapturedRunSpawnSpec
    lease: CapturedRunLeaseHandle
    terminal: TerminalPty
    terminal_output: TerminalFanout
    created_at: datetime
    started_at: datetime
    updated_at: datetime
    viewerless_since: datetime | None
    exit_code: int | None
    end_reason: str | None
    error: str | None
    # None when the bridge should stay silent (osc_color_replies disabled).
    osc_responder: OscColorResponder | None
    drain_task: asyncio.Task[None] = field(init=False)

    @property
    def scrollback(self) -> ScrollbackRing:
        return self.terminal_output.scrollback

    @property
    def attachments(self) -> dict[str, TerminalAttachment]:
        return self.terminal_output.attachments

    def view(self) -> ManagedRunView:
        return ManagedRunView(
            run_id=self.run_id,
            cli=self.cli,
            cwd=self.cwd,
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
        spawn_concurrency: int = 6,
        session_store_preflight_ttl: timedelta = _SESSION_STORE_PREFLIGHT_CACHE_TTL,
        shared_proxy_manager: SharedProxyManager | None = None,
    ) -> None:
        if spawn_concurrency < 1:
            raise ValueError("spawn_concurrency must be at least 1")
        self._dependencies = dependencies or default_claude_run_dependencies()
        self._prepare_run = prepare_run
        self._spawn_pty = spawn_pty
        self._clock = clock
        self._scrollback_bytes = scrollback_bytes
        self._attachment_queue_size = attachment_queue_size
        self._read_chunk_size = read_chunk_size
        self._install_signal_handlers = install_signal_handlers
        self._runs: dict[str, ManagedRun] = {}
        self._runs_by_idempotency_key: dict[str, ManagedRun] = {}
        self._spawn_idempotency_lock = asyncio.Lock()
        self._spawn_semaphore = asyncio.Semaphore(spawn_concurrency)
        self._session_store_preflight_lock = asyncio.Lock()
        self._session_store_preflight_ttl = session_store_preflight_ttl
        self._session_store_preflight_ok_until: datetime | None = None
        self._shared_proxy_manager = shared_proxy_manager
        self._teardown_lock = asyncio.Lock()
        self._closed = False

    async def spawn(self, request: SpawnRun) -> ManagedRun:
        if self._closed:
            raise RunManagerError("run_manager_closed", "run manager is closed")
        if request.idempotency_key is None:
            return await self._spawn_new(self._validate_spawn_request(request))
        async with self._spawn_idempotency_lock:
            existing = self._runs_by_idempotency_key.get(request.idempotency_key)
            if existing is not None:
                return existing
            run = await self._spawn_new(self._validate_spawn_request(request))
            self._runs_by_idempotency_key[request.idempotency_key] = run
            return run

    async def _spawn_new(self, validated: _ValidatedSpawnRun) -> ManagedRun:
        async with self._spawn_semaphore:
            return await self._spawn_new_admitted(validated)

    async def _spawn_new_admitted(self, validated: _ValidatedSpawnRun) -> ManagedRun:
        request = validated.request
        if self._closed:
            raise RunManagerError("run_manager_closed", "run manager is closed")

        spawn_spec, lease = await self._prepare_request(validated)
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
                terminal_output=TerminalFanout(
                    clock=self._clock,
                    scrollback_bytes=self._scrollback_bytes,
                    attachment_queue_size=self._attachment_queue_size,
                ),
                created_at=now,
                started_at=now,
                updated_at=now,
                viewerless_since=now,
                exit_code=None,
                end_reason=None,
                error=None,
                osc_responder=OscColorResponder() if request.osc_color_replies else None,
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
            if filters.cwd is not None:
                runs = tuple(run for run in runs if run.cwd == filters.cwd)
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
        if run.state is RunState.TERMINATED:
            raise RunManagerError("run_terminated", f"run {run_id} was terminated")
        if run.terminal.closed:
            raise RunManagerError("run_stale", f"run {run_id} has no live terminal")
        if run.state is not RunState.RUNNING:
            raise RunManagerError("run_not_attachable", f"run {run_id} is {run.state}")
        attached = run.terminal_output.attach(
            cols=cols,
            rows=rows,
            attachment_id=attachment_id,
            queue_maxsize=queue_maxsize,
        )
        run.viewerless_since = None
        run.updated_at = self._clock()
        return attached

    def detach(self, run_id: str, attachment_id: str) -> None:
        run = self.get(run_id)
        self._detach(run, attachment_id)

    async def terminate(
        self, run_id: str, *, reason: TerminateReason = "explicit"
    ) -> ManagedRunView:
        run = self.get(run_id)
        await self._teardown_run(run, force=True, reason=reason)
        return run.view()

    async def close(self) -> None:
        self._closed = True
        runs = [run for run in self._runs.values() if run.state not in _TERMINAL_STATES]
        for run in runs:
            await self._teardown_run(run, force=True, reason="shutdown")

    async def _prepare_request(
        self, validated: _ValidatedSpawnRun
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLeaseHandle]:
        await self._ensure_session_store_available()
        captured_request = self._captured_request(validated)
        if (
            captured_request.web_runtime == WEB_RUNTIME_EXTERNAL
            and self._shared_proxy_manager is not None
        ):
            try:
                return await prepare_shared_captured_run(
                    captured_request,
                    shared_proxy=self._shared_proxy_manager,
                    dependencies=self._dependencies,
                )
            except CapturedRunBindConflict as exc:
                raise RunManagerError("bind_conflict", str(exc)) from exc
            except CapturedRunProxyStartTimeout as exc:
                raise RunManagerError("proxy_start_timeout", str(exc)) from exc
            except RunManagerError:
                raise
            except Exception as exc:
                raise RunManagerError("launch_failed", str(exc)) from exc
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
        except CapturedRunProxyStartTimeout as exc:
            raise RunManagerError("proxy_start_timeout", str(exc)) from exc
        except RunManagerError:
            raise
        except Exception as exc:
            raise RunManagerError("launch_failed", str(exc)) from exc

    def _validate_spawn_request(self, request: SpawnRun) -> _ValidatedSpawnRun:
        if request.cli not in _VALID_CAPTURED_RUN_CLIS:
            raise RunManagerError("unsupported_cli", f"unsupported captured run cli: {request.cli}")
        cwd = self._resolve_cwd(request.cwd)
        upstream = request.upstream
        if upstream is None:
            upstream = CLAUDE_UPSTREAM_DEFAULT if request.cli == CLAUDE_CLIENT_NAME else ""
        return _ValidatedSpawnRun(request=request, cwd=cwd, upstream=upstream)

    def _captured_request(self, validated: _ValidatedSpawnRun) -> CapturedRunRequest:
        request = validated.request
        return CapturedRunRequest(
            client_name=request.cli,
            passthrough=request.passthrough,
            directory=validated.cwd,
            proxy_port=request.proxy_port,
            web_port=request.web_port,
            upstream=validated.upstream,
            storage_dir=request.storage_dir,
            home_dir=request.home_dir,
            client_bin=request.client_bin,
            client_disabled=request.client_disabled,
            no_system_prompt=request.no_system_prompt,
            debug=request.debug,
            web_runtime=request.web_runtime,
            default_client_passthrough=request.default_client_passthrough,
            runtime_template=request.runtime_template,
            launch_fields=request.launch_fields,
        )

    async def _ensure_session_store_available(self) -> None:
        if self._session_store_preflight_cache_valid():
            return
        async with self._session_store_preflight_lock:
            if self._session_store_preflight_cache_valid():
                return
            store_error = await asyncio.to_thread(self._dependencies.check_session_store)
            if store_error is not None:
                raise RunManagerError("session_store_unavailable", store_error)
            self._session_store_preflight_ok_until = (
                self._clock() + self._session_store_preflight_ttl
            )

    def _session_store_preflight_cache_valid(self) -> bool:
        ok_until = self._session_store_preflight_ok_until
        return ok_until is not None and self._clock() < ok_until

    def _resolve_cwd(self, cwd: Path | None) -> Path:
        working_dir = Path.cwd() if cwd is None else cwd.expanduser()
        if not working_dir.is_absolute():
            raise RunManagerError("invalid_cwd", "cwd must be an absolute path")
        if not working_dir.exists():
            raise RunManagerError("invalid_cwd", f"cwd does not exist: {working_dir}")
        if not working_dir.is_dir():
            raise RunManagerError("invalid_cwd", f"cwd is not a directory: {working_dir}")
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
            await self._teardown_run(run, force=False, reason="natural-exit")
            return

        logger.error(
            "managed run drain failed",
            exc_info=(type(failure), failure, failure.__traceback__),
        )
        await self._teardown_run(run, force=False, reason="failed", failure=failure)

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
        if run.state not in {RunState.RUNNING, RunState.TERMINATING}:
            return
        if run.osc_responder is not None:
            # Answer color queries inside the CLI's startup window; an fd that
            # closed mid-callback just drops the reply (the CLI is exiting).
            for reply in run.osc_responder.replies_for(data):
                with contextlib.suppress(OSError):
                    write_all(run.terminal.master_fd, reply)
        _, closed_attachment_ids = run.terminal_output.append(data, emitted_at=now)
        run.updated_at = now
        if closed_attachment_ids and not run.attachments and run.state is RunState.RUNNING:
            run.viewerless_since = now

    async def _teardown_run(
        self,
        run: ManagedRun,
        *,
        force: bool,
        reason: RunEndReason,
        failure: BaseException | None = None,
    ) -> None:
        async with self._teardown_lock:
            if run.state in _TERMINAL_STATES and run.terminal.closed:
                return

            run.state = RunState.TERMINATING if force else RunState.EXITED
            if reason == "failed":
                run.state = RunState.FAILED
            run.end_reason = (
                reason
                if reason in {"explicit", "shutdown", "idle-timeout", "deploy-restart"}
                else None
            )
            run.error = str(failure) if failure is not None else None
            run.updated_at = self._clock()
            self._close_all_attachments(
                run,
                code="run-ended",
                retryable=False,
                message=f"run ended: {run.state}",
            )

            current_task = asyncio.current_task()
            if run.drain_task is not current_task and not run.drain_task.done():
                run.drain_task.cancel()
                self._remove_reader(run.terminal.master_fd)
                with contextlib.suppress(asyncio.CancelledError):
                    await run.drain_task

            self._remove_reader(run.terminal.master_fd)
            if force:
                await asyncio.to_thread(terminate_terminal_pty, run.terminal)
            else:
                await asyncio.to_thread(close_terminal_master, run.terminal)
            await self._close_lease(run.lease)

            run.exit_code = run.terminal.process.poll()
            if run.state is RunState.TERMINATING:
                run.state = RunState.TERMINATED
            run.updated_at = self._clock()

    async def _rollback_post_prepare(
        self,
        *,
        terminal: TerminalPty | None,
        drain_task: asyncio.Task[None] | None,
        lease: CapturedRunLeaseHandle,
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
        await self._close_lease(lease)

    async def _close_lease(self, lease: CapturedRunLeaseHandle) -> None:
        aclose = getattr(lease, "aclose", None)
        if aclose is not None:
            await aclose()
            return
        await asyncio.to_thread(lease.close)

    def _close_all_attachments(
        self,
        run: ManagedRun,
        *,
        code: str,
        retryable: bool,
        message: str,
    ) -> None:
        run.terminal_output.close_all(code=code, retryable=retryable, message=message)

    def _detach(self, run: ManagedRun, attachment_id: str) -> None:
        run.terminal_output.detach(attachment_id)
        if not run.attachments and run.state is RunState.RUNNING:
            run.viewerless_since = self._clock()
        run.updated_at = self._clock()

    def _remove_reader(self, fd: int) -> None:
        with contextlib.suppress(RuntimeError, ValueError, OSError):
            asyncio.get_running_loop().remove_reader(fd)


_TERMINAL_STATES = frozenset({RunState.TERMINATED, RunState.EXITED, RunState.FAILED})
_VALID_CAPTURED_RUN_CLIS = frozenset({CLAUDE_CLIENT_NAME, CODEX_CLIENT_NAME})
