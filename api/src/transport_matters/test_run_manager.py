from __future__ import annotations

import ast
import asyncio
import contextlib
import os
import threading
import tty
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
from transport_matters.run_terminal import SLOW_VIEWER_CLOSE_CODE, PtyChunk

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
        SpawnRun(harness="claude", cwd=tmp_path, web_runtime=WEB_RUNTIME_EMBEDDED)
    )


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
    attached = manager.attach(run.run_id, cols=80, rows=24, attachment_id="viewer")
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
    pty.write(run.terminal, b"headless-output")

    await wait_until(
        lambda: b"headless-output" in b"".join(c.data for c in run.scrollback.snapshot())
    )
    assert run.attachments == {}
    assert run.state is RunState.RUNNING

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
            SpawnRun(harness="claude", cwd=tmp_path, web_runtime=WEB_RUNTIME_EMBEDDED)
        )

    assert prepared.leases[0].close_count == 1


async def test_idempotency_key_returns_existing_run_without_reprepare(tmp_path: Path) -> None:
    pty = PtyHarness()
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)

    first = await manager.spawn(
        SpawnRun(
            harness="claude",
            cwd=tmp_path,
            web_runtime=WEB_RUNTIME_EMBEDDED,
            idempotency_key="retry-1",
        )
    )
    second = await manager.spawn(
        SpawnRun(
            harness="claude",
            cwd=tmp_path,
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
            cwd=tmp_path,
            web_runtime=WEB_RUNTIME_EMBEDDED,
            idempotency_key="fork-a",
        )
    )
    second = await manager.spawn(
        SpawnRun(
            harness="claude",
            cwd=tmp_path,
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
            cwd=tmp_path,
            web_runtime=WEB_RUNTIME_EMBEDDED,
            runtime_template=runtime_template,
        )
    )

    assert len(prepared.requests) == 1
    assert prepared.requests[0].runtime_template is runtime_template


async def test_close_during_in_flight_spawn_rolls_back_prepared_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pty = PtyHarness()
    patch_pty_teardown(monkeypatch, pty)
    prepared = BlockingPreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)

    spawn_task = asyncio.create_task(
        manager.spawn(SpawnRun(harness="claude", cwd=tmp_path, web_runtime=WEB_RUNTIME_EMBEDDED))
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


async def test_teardown_removes_reader_before_closing_master(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    pty = PtyHarness(events)
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path, events=events)
    manager = make_manager(tmp_path, pty, prepared, events=events)

    run = await spawn_run(manager, tmp_path)
    await manager.terminate(run.run_id)

    assert events.index("remove_reader") < events.index("terminate")


async def test_reattach_receives_scrollback_then_live_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pty = PtyHarness()
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)

    run = await spawn_run(manager, tmp_path)
    pty.write(run.terminal, b"past")
    await wait_until(lambda: b"past" in b"".join(c.data for c in run.scrollback.snapshot()))

    attached = manager.attach(run.run_id, cols=80, rows=24, attachment_id="viewer-1")
    assert b"past" in b"".join(chunk.data for chunk in attached.scrollback)

    pty.write(run.terminal, b"live")
    live_item = await asyncio.wait_for(attached.attachment.queue.get(), timeout=1)
    assert isinstance(live_item, PtyChunk)
    assert live_item.data == b"live"

    manager.detach(run.run_id, attached.attachment.attachment_id)
    reattached = manager.attach(run.run_id, cols=80, rows=24, attachment_id="viewer-2")
    replay = b"".join(chunk.data for chunk in reattached.scrollback)
    assert b"past" in replay
    assert b"live" in replay

    await manager.close()


async def test_explicit_terminate_terminates_pty_before_lease_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    pty = PtyHarness(events)
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path, events=events)
    manager = make_manager(tmp_path, pty, prepared, events=events)

    run = await spawn_run(manager, tmp_path)
    view = await manager.terminate(run.run_id)

    assert view.state is RunState.TERMINATED
    assert view.end_reason == "explicit"
    assert events.index("terminate") < events.index("lease.close")


async def test_explicit_terminate_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    pty = PtyHarness(events)
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path, events=events)
    manager = make_manager(tmp_path, pty, prepared, events=events)

    run = await spawn_run(manager, tmp_path)
    first = await manager.terminate(run.run_id)
    second = await manager.terminate(run.run_id)

    assert first.state is RunState.TERMINATED
    assert second.state is RunState.TERMINATED
    assert prepared.leases[0].close_count == 1
    assert events.count("terminate") == 1
    assert events.count("lease.close") == 1


async def test_close_terminates_multiple_running_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    pty = PtyHarness(events)
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path, events=events)
    manager = make_manager(tmp_path, pty, prepared, events=events)

    run_a = await spawn_run(manager, tmp_path)
    run_b = await spawn_run(manager, tmp_path)
    await manager.close()

    assert run_a.state is RunState.TERMINATED
    assert run_b.state is RunState.TERMINATED
    assert [lease.close_count for lease in prepared.leases] == [1, 1]
    assert events.count("terminate") == 2
    assert events.count("lease.close") == 2


async def test_attach_errors_distinguish_terminated_and_stale_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pty = PtyHarness()
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)

    terminated = await spawn_run(manager, tmp_path)
    await manager.terminate(terminated.run_id)
    with pytest.raises(RunManagerError) as terminated_error:
        manager.attach(terminated.run_id, cols=80, rows=24)
    assert terminated_error.value.code == "run_terminated"

    stale = await spawn_run(manager, tmp_path)
    pty.close_master(stale.terminal)
    with pytest.raises(RunManagerError) as stale_error:
        manager.attach(stale.run_id, cols=80, rows=24)
    assert stale_error.value.code == "run_stale"
    await manager.close()


async def test_slow_viewer_is_closed_without_stopping_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pty = PtyHarness()
    patch_pty_teardown(monkeypatch, pty)
    prepared = PreparedRunHarness(tmp_path)
    manager = make_manager(tmp_path, pty, prepared)

    run = await spawn_run(manager, tmp_path)
    attached = manager.attach(run.run_id, cols=80, rows=24, attachment_id="slow", queue_maxsize=1)

    pty.write(run.terminal, b"first")
    await wait_until(lambda: attached.attachment.queue.qsize() == 1)
    pty.write(run.terminal, b"second")
    await wait_until(lambda: "slow" not in run.attachments)

    assert attached.attachment.closed_reason == SLOW_VIEWER_CLOSE_CODE
    assert run.state is RunState.RUNNING
    first_item = attached.attachment.queue.get_nowait()
    assert isinstance(first_item, PtyChunk)

    await manager.close()


class OpenPtyHarness:
    """PtyHarness's pipes cannot observe what the manager writes back into PTY
    input, so the OSC responder tests use a real openpty pair: the test plays
    the CLI on the slave side, writing queries and reading the bridge's
    replies."""

    def __init__(self) -> None:
        self.slave_fds: dict[int, int] = {}
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
        master_fd, slave_fd = os.openpty()
        # Raw mode, as a real CLI sets it: without it the slave's canonical
        # input buffering holds the newline-less reply forever.
        tty.setraw(slave_fd)
        os.set_blocking(slave_fd, False)
        process = FakeProcess()
        self.slave_fds[master_fd] = slave_fd
        self.processes[master_fd] = process
        return TerminalPty(master_fd=master_fd, process=cast("Any", process))

    def child_write(self, terminal: TerminalPty, data: bytes) -> None:
        os.write(self.slave_fds[terminal.master_fd], data)

    def child_read(self, terminal: TerminalPty) -> bytes:
        try:
            return os.read(self.slave_fds[terminal.master_fd], 4096)
        except BlockingIOError:
            return b""

    def terminate(self, terminal: TerminalPty) -> None:
        self.processes[terminal.master_fd].returncode = -15
        self.close_master(terminal)

    def close_master(self, terminal: TerminalPty) -> None:
        if not terminal.closed:
            with contextlib.suppress(OSError):
                os.close(terminal.master_fd)
            terminal.closed = True
        slave_fd = self.slave_fds.pop(terminal.master_fd, None)
        if slave_fd is not None:
            with contextlib.suppress(OSError):
                os.close(slave_fd)


async def test_bridge_answers_cli_osc_color_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from transport_matters.osc_color_responder import OSC_BACKGROUND_REPLY

    pty = OpenPtyHarness()
    monkeypatch.setattr(run_manager_module, "terminate_terminal_pty", pty.terminate)
    monkeypatch.setattr(run_manager_module, "close_terminal_master", pty.close_master)
    prepared = PreparedRunHarness(tmp_path)
    manager = RunManager(
        dependencies=fake_dependencies(),
        prepare_run=prepared.prepare,
        spawn_pty=pty.spawn,
        scrollback_bytes=4096,
        attachment_queue_size=8,
    )

    run = await spawn_run(manager, tmp_path)
    pty.child_write(run.terminal, b"\x1b]11;?\x07")

    received = bytearray()

    def reply_arrived() -> bool:
        received.extend(pty.child_read(run.terminal))
        return OSC_BACKGROUND_REPLY in received

    await wait_until(reply_arrived)
    await manager.close()


async def test_disabled_osc_color_replies_stay_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pty = OpenPtyHarness()
    monkeypatch.setattr(run_manager_module, "terminate_terminal_pty", pty.terminate)
    monkeypatch.setattr(run_manager_module, "close_terminal_master", pty.close_master)
    prepared = PreparedRunHarness(tmp_path)
    manager = RunManager(
        dependencies=fake_dependencies(),
        prepare_run=prepared.prepare,
        spawn_pty=pty.spawn,
        scrollback_bytes=4096,
        attachment_queue_size=8,
    )

    run = await manager.spawn(
        SpawnRun(
            harness="claude",
            cwd=tmp_path,
            web_runtime=WEB_RUNTIME_EMBEDDED,
            osc_color_replies=False,
        )
    )
    pty.child_write(run.terminal, b"\x1b]11;?\x07")
    # Give the drain loop time to swallow the query, then prove no reply came.
    await wait_until(lambda: run.scrollback.total_bytes > 0)
    await asyncio.sleep(0.05)
    assert pty.child_read(run.terminal) == b""
    await manager.close()
