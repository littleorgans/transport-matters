from __future__ import annotations

import ast
import asyncio
import contextlib
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest

import transport_matters.run_manager as run_manager_module
from transport_matters.captured_run import (
    WEB_RUNTIME_EMBEDDED,
    CapturedRunDependencies,
    CapturedRunLease,
    CapturedRunRequest,
    CapturedRunSpawnSpec,
)
from transport_matters.cli.runner import ManagedClient
from transport_matters.cli.runtime_home import RuntimeTemplateRef
from transport_matters.pty_session import TerminalPty
from transport_matters.run_manager import (
    ManagedRun,
    RunManager,
    RunManagerError,
    RunState,
    SpawnRun,
)
from transport_matters.space.models import ResolvedWorktree, SpaceId, WorktreeId
from transport_matters.run_terminal import PtyChunk

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class FakeLease:
    def __init__(self, events: list[str] | None = None) -> None:
        self.close_count = 0
        self.events = events

    def close(self) -> None:
        self.close_count += 1
        if self.events is not None:
            self.events.append("lease.close")


class FakeProcess:
    def __init__(self) -> None:
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


class PtyHarness:
    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events
        self.write_fds: dict[int, int] = {}
        self.processes: dict[int, FakeProcess] = {}

    def spawn(
        self,
        *,
        argv: Sequence[str],
        env: Mapping[str, str],
        cwd: Path,
        cols: int,
        rows: int,
    ) -> TerminalPty:
        _ = (argv, env, cwd, cols, rows)
        read_fd, write_fd = os.pipe()
        process = FakeProcess()
        self.write_fds[read_fd] = write_fd
        self.processes[read_fd] = process
        return TerminalPty(master_fd=read_fd, process=cast("Any", process))

    def write(self, terminal: TerminalPty, data: bytes) -> None:
        os.write(self.write_fds[terminal.master_fd], data)

    def terminate(self, terminal: TerminalPty) -> None:
        if self.events is not None:
            self.events.append("terminate")
        self.processes[terminal.master_fd].returncode = -15
        self._close_terminal_fds(terminal)

    def close_master(self, terminal: TerminalPty) -> None:
        if self.events is not None:
            self.events.append("close_master")
        self._close_terminal_fds(terminal)

    def _close_terminal_fds(self, terminal: TerminalPty) -> None:
        if not terminal.closed:
            with contextlib.suppress(OSError):
                os.close(terminal.master_fd)
            terminal.closed = True
        write_fd = self.write_fds.pop(terminal.master_fd, None)
        if write_fd is not None:
            with contextlib.suppress(OSError):
                os.close(write_fd)


class StartupWritingPtyHarness(PtyHarness):
    def spawn(
        self,
        *,
        argv: Sequence[str],
        env: Mapping[str, str],
        cwd: Path,
        cols: int,
        rows: int,
    ) -> TerminalPty:
        terminal = super().spawn(argv=argv, env=env, cwd=cwd, cols=cols, rows=rows)
        os.write(self.write_fds[terminal.master_fd], b"startup-frame")
        return terminal


class PreparedRunHarness:
    def __init__(self, tmp_path: Path, *, events: list[str] | None = None) -> None:
        self.tmp_path = tmp_path
        self.events = events
        self.leases: list[FakeLease] = []
        self.requests: list[CapturedRunRequest] = []

    def prepare(
        self,
        request: CapturedRunRequest,
        **_: object,
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
        self.requests.append(request)
        lease = FakeLease(self.events)
        self.leases.append(lease)
        cwd = request.directory or self.tmp_path
        client = ManagedClient(
            name=request.harness,
            display_name=request.harness.title(),
            argv=["fake-agent"],
            env={},
            cwd=cwd,
        )
        spawn_spec = CapturedRunSpawnSpec(
            run_id=f"run-{uuid4().hex}",
            working_dir=cwd,
            storage_dir=self.tmp_path,
            proxy_port=8787,
            web_port=None,
            mitmdump_log=self.tmp_path / "mitmdump.log",
            client=client,
            launch_env={},
            managed_session=None,
            harness=request.harness,
        )
        return spawn_spec, cast("CapturedRunLease", lease)


class BlockingPreparedRunHarness(PreparedRunHarness):
    def __init__(self, tmp_path: Path, *, events: list[str] | None = None) -> None:
        super().__init__(tmp_path, events=events)
        self.entered = threading.Event()
        self.release = threading.Event()

    def prepare(
        self,
        request: CapturedRunRequest,
        **kwargs: object,
    ) -> tuple[CapturedRunSpawnSpec, CapturedRunLease]:
        self.entered.set()
        if not self.release.wait(timeout=1.0):
            raise AssertionError("blocked prepare was not released")
        return super().prepare(request, **kwargs)


class RecordingRunManager(RunManager):
    def __init__(self, *args: Any, events: list[str], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.events = events

    def _remove_reader(self, fd: int) -> None:
        self.events.append("remove_reader")
        super()._remove_reader(fd)


def resolved_worktree(
    tmp_path: Path,
    *,
    space_id: SpaceId | None = None,
    worktree_id: WorktreeId | None = None,
    missing: bool = False,
    archived: bool = False,
) -> ResolvedWorktree:
    return ResolvedWorktree(
        space_id=space_id or SpaceId.from_uuid(uuid4()),
        worktree_id=worktree_id or WorktreeId.from_uuid(uuid4()),
        cwd=str(tmp_path),
        workspace_slug="workspace",
        workspace_hash="hash1",
        missing=missing,
        archived=archived,
    )


def fake_dependencies() -> CapturedRunDependencies:
    return CapturedRunDependencies(
        require_addon=lambda: Path("addon.py"),
        resolve_mitmdump=lambda: "mitmdump",
        which=lambda *_: "fake",
        port_in_use=lambda _: False,
        allocate_port_pair=lambda: (8787, 8788),
        inject_system_prompt=lambda passthrough, **_: list(passthrough),
        user_supplied_system_prompt=lambda _: False,
        check_session_store=lambda: None,
    )


def make_manager(
    tmp_path: Path,
    pty: PtyHarness,
    prepared: PreparedRunHarness,
    *,
    events: list[str] | None = None,
    shared_proxy_manager: object | None = None,
    shared_proxy_unavailable_reason: str | None = None,
) -> RunManager:
    manager_type = RecordingRunManager if events is not None else RunManager
    kwargs: dict[str, Any] = {"events": events} if events is not None else {}
    return manager_type(
        dependencies=fake_dependencies(),
        prepare_run=prepared.prepare,
        spawn_pty=pty.spawn,
        scrollback_bytes=64,
        attachment_queue_size=8,
        shared_proxy_manager=cast("Any", shared_proxy_manager),
        shared_proxy_unavailable_reason=shared_proxy_unavailable_reason,
        **kwargs,
    )


async def wait_until(predicate: Any, *, seconds: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + seconds
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def patch_pty_teardown(monkeypatch: pytest.MonkeyPatch, pty: PtyHarness) -> None:
    monkeypatch.setattr(run_manager_module, "terminate_terminal_pty", pty.terminate)
    monkeypatch.setattr(run_manager_module, "close_terminal_master", pty.close_master)


async def spawn_run(manager: RunManager, tmp_path: Path) -> ManagedRun:
    return await manager.spawn(
        SpawnRun(harness="claude", resolved_worktree=resolved_worktree(tmp_path), web_runtime=WEB_RUNTIME_EMBEDDED)
    )


def require_terminal(run: ManagedRun) -> TerminalPty:
    assert run.terminal is not None
    return run.terminal


def test_package_root_seams_do_not_import_api() -> None:
    api_root = Path(__file__).resolve().parents[2]
    for relative in (
        Path("src/transport_matters/captured_run_models.py"),
        Path("src/transport_matters/run_manager.py"),
        Path("src/transport_matters/run_terminal.py"),
        Path("src/transport_matters/pty_session.py"),
    ):
        tree = ast.parse((api_root / relative).read_text())
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.append(node.module)
        assert not any(module.startswith("transport_matters.api") for module in imported)


async def test_detach_does_not_close_run_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    pty = PtyHarness(events)
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path, events=events)
    manager = make_manager(tmp_path, pty, prepared, events=events)

    run = await spawn_run(manager, tmp_path)
    attached = await manager.attach(run.run_id, cols=80, rows=24, attachment_id="viewer")
    manager.detach(run.run_id, attached.attachment.attachment_id)

    assert prepared.leases[0].close_count == 0
    assert run.state is RunState.RUNNING
    assert run.attachments == {}

    await manager.close()


async def test_headless_run_drains_pty_output_into_scrollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pty = PtyHarness()
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)

    run = await spawn_run(manager, tmp_path)
    pty.write(require_terminal(run), b"headless-output")

    await wait_until(
        lambda: b"headless-output" in b"".join(c.data for c in run.scrollback.snapshot())
    )
    assert run.attachments == {}
    assert run.state is RunState.RUNNING

    await manager.close()


async def test_start_on_attach_registers_viewer_before_pty_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pty = StartupWritingPtyHarness()
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)

    run = await manager.spawn(
        SpawnRun(
            harness="claude",
            resolved_worktree=resolved_worktree(tmp_path),
            web_runtime=WEB_RUNTIME_EMBEDDED,
            start_on_attach=True,
        )
    )

    assert run.terminal is None
    assert run.scrollback.snapshot() == ()

    attached = await manager.attach(run.run_id, cols=80, rows=24, attachment_id="viewer")
    item = await asyncio.wait_for(attached.attachment.queue.get(), timeout=1)

    assert isinstance(item, PtyChunk)
    assert item.data == b"startup-frame"
    assert attached.scrollback == ()

    await manager.close()


async def test_post_prepare_spawn_failure_closes_lease(tmp_path: Path) -> None:
    prepared = PreparedRunHarness(tmp_path)

    def spawn_failure(**_: object) -> TerminalPty:
        raise RuntimeError("pty spawn failed")

    manager = RunManager(
        dependencies=fake_dependencies(),
        prepare_run=prepared.prepare,
        spawn_pty=spawn_failure,
    )

    with pytest.raises(RunManagerError, match="pty spawn failed"):
        await manager.spawn(
            SpawnRun(harness="claude", resolved_worktree=resolved_worktree(tmp_path), web_runtime=WEB_RUNTIME_EMBEDDED)
        )

    assert prepared.leases[0].close_count == 1


async def test_idempotency_key_returns_existing_run_without_reprepare(tmp_path: Path) -> None:
    pty = PtyHarness()
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)

    first = await manager.spawn(
        SpawnRun(
            harness="claude",
            resolved_worktree=resolved_worktree(tmp_path),
            web_runtime=WEB_RUNTIME_EMBEDDED,
            idempotency_key="retry-1",
        )
    )
    second = await manager.spawn(
        SpawnRun(
            harness="claude",
            resolved_worktree=resolved_worktree(tmp_path),
            web_runtime=WEB_RUNTIME_EMBEDDED,
            idempotency_key="retry-1",
        )
    )

    assert second is first
    assert len(prepared.requests) == 1
    assert len(prepared.leases) == 1


async def test_different_idempotency_keys_spawn_distinct_runs(tmp_path: Path) -> None:
    pty = PtyHarness()
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)

    first = await manager.spawn(
        SpawnRun(
            harness="claude",
            resolved_worktree=resolved_worktree(tmp_path),
            web_runtime=WEB_RUNTIME_EMBEDDED,
            idempotency_key="fork-a",
        )
    )
    second = await manager.spawn(
        SpawnRun(
            harness="claude",
            resolved_worktree=resolved_worktree(tmp_path),
            web_runtime=WEB_RUNTIME_EMBEDDED,
            idempotency_key="fork-b",
        )
    )

    assert second is not first
    assert len(prepared.requests) == 2


async def test_spawn_passes_runtime_template_to_captured_request(tmp_path: Path) -> None:
    pty = PtyHarness()
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)
    runtime_template = RuntimeTemplateRef(
        template_id="codex-base",
        harness="codex",
        template_home=tmp_path / "template",
        provenance={"registry_source": "agent-runtimes"},
    )

    await manager.spawn(
        SpawnRun(
            harness="codex",
            resolved_worktree=resolved_worktree(tmp_path),
            web_runtime=WEB_RUNTIME_EMBEDDED,
            runtime_template=runtime_template,
        )
    )

    assert len(prepared.requests) == 1
    assert prepared.requests[0].runtime_template is runtime_template


async def test_spawn_passes_bypass_permissions_to_captured_request(tmp_path: Path) -> None:
    pty = PtyHarness()
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)

    await manager.spawn(
        SpawnRun(
            harness="claude",
            resolved_worktree=resolved_worktree(tmp_path),
            web_runtime=WEB_RUNTIME_EMBEDDED,
            bypass_permissions=True,
        )
    )

    assert len(prepared.requests) == 1
    assert prepared.requests[0].bypass_permissions is True


async def test_close_during_in_flight_spawn_rolls_back_prepared_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pty = PtyHarness()
    patch_pty_teardown(monkeypatch, pty)
    prepared = BlockingPreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)

    spawn_task = asyncio.create_task(
        manager.spawn(SpawnRun(harness="claude", resolved_worktree=resolved_worktree(tmp_path), web_runtime=WEB_RUNTIME_EMBEDDED))
    )
    assert await asyncio.to_thread(prepared.entered.wait, 1.0)

    await manager.close()
    prepared.release.set()

    with pytest.raises(RunManagerError) as exc_info:
        await spawn_task

    assert exc_info.value.code == "run_manager_closed"
    assert manager.list() == []
    assert len(prepared.leases) == 1
    assert prepared.leases[0].close_count == 1
