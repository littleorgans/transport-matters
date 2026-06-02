"""Tests for pause-count task tracking and drain logic."""

import asyncio
import logging

import pytest

from transport_matters import pause_session


@pytest.fixture(autouse=True)
def _reset_pause_count_tasks() -> None:
    """Isolate the module-global task set between tests."""
    pause_session._pause_count_tasks.clear()


# ---------------------------------------------------------------------------
# drain_pause_count_tasks
# ---------------------------------------------------------------------------


async def test_drain_empty_set_is_noop() -> None:
    """drain on an empty set returns without error."""
    assert len(pause_session._pause_count_tasks) == 0
    await pause_session.drain_pause_count_tasks()  # must not raise


async def test_drain_awaits_finishing_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """A task that completes within the timeout is awaited; set ends empty."""
    monkeypatch.setattr(pause_session, "_PAUSE_DRAIN_TIMEOUT_S", 2.0)

    finished = asyncio.Event()

    async def quick_work() -> None:
        finished.set()

    task: asyncio.Task[None] = asyncio.create_task(quick_work(), name="pause-count:test-1")
    pause_session._pause_count_tasks.add(task)
    task.add_done_callback(pause_session._retire_pause_count_task)

    await pause_session.drain_pause_count_tasks()

    assert finished.is_set()
    assert task.done()
    assert not task.cancelled()
    # retire callback should have discarded from the set
    assert task not in pause_session._pause_count_tasks


async def test_drain_cancels_straggler(monkeypatch: pytest.MonkeyPatch) -> None:
    """A task that exceeds the (tiny) timeout is cancelled by drain."""
    monkeypatch.setattr(pause_session, "_PAUSE_DRAIN_TIMEOUT_S", 0.01)

    async def slow_work() -> None:
        await asyncio.sleep(60)

    task: asyncio.Task[None] = asyncio.create_task(slow_work(), name="pause-count:straggler")
    pause_session._pause_count_tasks.add(task)
    task.add_done_callback(pause_session._retire_pause_count_task)

    await pause_session.drain_pause_count_tasks()
    # Give the event loop a tick so the cancellation propagates
    await asyncio.sleep(0)

    assert task.cancelled()


# ---------------------------------------------------------------------------
# _retire_pause_count_task
# ---------------------------------------------------------------------------


async def test_retire_discards_task_from_set() -> None:
    """_retire_pause_count_task removes the task from the global set."""

    async def noop() -> None:
        pass

    task: asyncio.Task[None] = asyncio.create_task(noop())
    pause_session._pause_count_tasks.add(task)
    await task  # let it finish
    pause_session._retire_pause_count_task(task)

    assert task not in pause_session._pause_count_tasks


async def test_retire_does_not_raise_on_failed_task(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_retire_pause_count_task swallows the exception and logs it."""

    async def boom() -> None:
        raise RuntimeError("intentional failure")

    task: asyncio.Task[None] = asyncio.create_task(boom())
    pause_session._pause_count_tasks.add(task)

    with pytest.raises(RuntimeError):
        await task  # consume the exception so asyncio doesn't warn

    with caplog.at_level(logging.ERROR, logger="transport_matters.pause_session"):
        pause_session._retire_pause_count_task(task)  # must not raise

    assert task not in pause_session._pause_count_tasks
    assert any("pause-count task failed" in r.message for r in caplog.records)
