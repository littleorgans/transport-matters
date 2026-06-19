from __future__ import annotations

import asyncio
import contextlib
import os
import tty
from typing import TYPE_CHECKING, Any, cast

import pytest

import transport_matters.run_manager as run_manager_module
from transport_matters.captured_run import WEB_RUNTIME_EMBEDDED
from transport_matters.pty_session import TerminalPty
from transport_matters.run_manager import RunManager, RunManagerError, RunState, SpawnRun
from transport_matters.run_terminal import SLOW_VIEWER_CLOSE_CODE, PtyChunk
from transport_matters.test_run_manager import (
    FakeProcess,
    PreparedRunHarness,
    PtyHarness,
    fake_dependencies,
    make_manager,
    patch_pty_teardown,
    require_terminal,
    spawn_run,
    wait_until,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path


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
    pty.write(require_terminal(run), b"past")
    await wait_until(lambda: b"past" in b"".join(c.data for c in run.scrollback.snapshot()))

    attached = await manager.attach(run.run_id, cols=80, rows=24, attachment_id="viewer-1")
    assert b"past" in b"".join(chunk.data for chunk in attached.scrollback)

    pty.write(require_terminal(run), b"live")
    live_item = await asyncio.wait_for(attached.attachment.queue.get(), timeout=1)
    assert isinstance(live_item, PtyChunk)
    assert live_item.data == b"live"

    manager.detach(run.run_id, attached.attachment.attachment_id)
    reattached = await manager.attach(run.run_id, cols=80, rows=24, attachment_id="viewer-2")
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
        await manager.attach(terminated.run_id, cols=80, rows=24)
    assert terminated_error.value.code == "run_terminated"

    stale = await spawn_run(manager, tmp_path)
    pty.close_master(require_terminal(stale))
    with pytest.raises(RunManagerError) as stale_error:
        await manager.attach(stale.run_id, cols=80, rows=24)
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
    attached = await manager.attach(
        run.run_id, cols=80, rows=24, attachment_id="slow", queue_maxsize=1
    )

    pty.write(require_terminal(run), b"first")
    await wait_until(lambda: attached.attachment.queue.qsize() == 1)
    pty.write(require_terminal(run), b"second")
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
    pty.child_write(require_terminal(run), b"\x1b]11;?\x07")

    received = bytearray()

    def reply_arrived() -> bool:
        received.extend(pty.child_read(require_terminal(run)))
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
    pty.child_write(require_terminal(run), b"\x1b]11;?\x07")
    # Give the drain loop time to swallow the query, then prove no reply came.
    await wait_until(lambda: run.scrollback.total_bytes > 0)
    await asyncio.sleep(0.05)
    assert pty.child_read(require_terminal(run)) == b""
    await manager.close()
