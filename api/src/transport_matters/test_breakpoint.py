"""Tests for the breakpoint state machine."""

import asyncio
from unittest.mock import MagicMock

import pytest

from transport_matters import breakpoint as bp
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset module-level state between tests."""
    bp.disarm()
    bp._paused.clear()


def _make_ir() -> InternalRequest:
    return InternalRequest(
        model="anthropic/claude-sonnet-4-20250514",
        provider="anthropic",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hi")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


def _mock_flow(flow_id: str = "flow-001") -> MagicMock:
    flow = MagicMock()
    flow.id = flow_id
    return flow


class TestArmDisarm:
    def test_arm_and_disarm(self) -> None:
        assert bp.get_mode() == "off"
        bp.arm()
        assert bp.get_mode() == "armed_once"
        bp.disarm()
        assert bp.get_mode() == "off"

    def test_is_armed_after_arm(self) -> None:
        assert not bp.is_armed()
        bp.arm()
        assert bp.is_armed()

    def test_import_time_default_is_off(self) -> None:
        """Regression: the import-time default must be 'off'.

        A prior version defaulted to 'armed_once' so the very first proxied
        request would pause unexpectedly. The autouse _reset_state fixture
        masks this by calling disarm() before every test, so we force a
        fresh module load here to see the actual default assignment.
        """
        import importlib

        importlib.reload(bp)
        assert bp._mode == "off"
        assert bp.get_mode() == "off"
        assert not bp.is_armed()


class TestPause:
    async def test_pause_stays_armed_and_registers(self) -> None:
        bp.arm()
        flow = _mock_flow()
        ir = _make_ir()

        event = await bp.pause(flow, ir, ir)

        assert bp.get_mode() == "armed_once"
        paused = await bp.get_paused()
        assert "flow-001" in paused
        assert not event.is_set()

        pf = paused["flow-001"]
        assert pf.curated_ir is ir
        assert pf.flow is flow
        assert pf.transport == "http"
        assert pf.paused_at_ms > 0


class TestRelease:
    async def test_release_sets_event(self) -> None:
        bp.arm()
        flow = _mock_flow()
        ir = _make_ir()
        event = await bp.pause(flow, ir, ir)

        mutated = _make_ir()
        ok = await bp.release("flow-001", mutated, b'{"ok":true}')

        assert ok is True
        assert event.is_set()
        paused = await bp.get_paused()
        pf = paused["flow-001"]
        assert pf.mutated_ir is mutated
        assert pf.release_payload == b'{"ok":true}'
        assert pf.dropped is False

    async def test_release_unknown_returns_false(self) -> None:
        assert await bp.release("nonexistent", _make_ir()) is False


class TestDrop:
    async def test_drop_sets_event(self) -> None:
        bp.arm()
        flow = _mock_flow()
        ir = _make_ir()
        event = await bp.pause(flow, ir, ir)

        ok = await bp.drop("flow-001")

        assert ok is True
        assert event.is_set()
        paused = await bp.get_paused()
        pf = paused["flow-001"]
        assert pf.dropped is True

    async def test_drop_unknown_returns_false(self) -> None:
        assert await bp.drop("nonexistent") is False


class TestPopPaused:
    async def test_pop_removes_and_returns(self) -> None:
        bp.arm()
        flow = _mock_flow()
        ir = _make_ir()
        await bp.pause(flow, ir, ir)

        pf = await bp.pop_paused("flow-001")
        assert pf is not None
        assert pf.flow is flow

        paused = await bp.get_paused()
        assert "flow-001" not in paused

    async def test_pop_missing_returns_none(self) -> None:
        assert await bp.pop_paused("nonexistent") is None


class TestClearAll:
    async def test_clear_all(self) -> None:
        bp.arm()
        flow1 = _mock_flow("f1")
        flow2 = _mock_flow("f2")
        ir = _make_ir()

        await bp.pause(flow1, ir, ir)
        bp.arm()
        await bp.pause(flow2, ir, ir)

        paused = await bp.get_paused()
        assert len(paused) == 2

        await bp.clear_all()

        # All flows should be marked dropped with events set
        paused = await bp.get_paused()
        for pf in paused.values():
            assert pf.dropped is True
            assert pf.event.is_set()


class TestConcurrency:
    async def test_concurrent_pause_release(self) -> None:
        """Two coroutines racing on pause and release should not corrupt state."""
        ir = _make_ir()
        results: list[bool] = []

        async def pause_and_release(flow_id: str) -> None:
            flow = _mock_flow(flow_id)
            bp.arm()
            await bp.pause(flow, ir, ir)
            ok = await bp.release(flow_id)
            results.append(ok)

        await asyncio.gather(
            pause_and_release("race-1"),
            pause_and_release("race-2"),
        )
        assert results == [True, True]
        paused = await bp.get_paused()
        # Both released: events set, still in dict (not popped)
        assert paused["race-1"].event.is_set()
        assert paused["race-2"].event.is_set()

    async def test_concurrent_pop_only_one_wins(self) -> None:
        """Two concurrent pop_paused calls for the same flow: only one gets the PausedFlow."""
        bp.arm()
        flow = _mock_flow("contested")
        ir = _make_ir()
        await bp.pause(flow, ir, ir)

        results = await asyncio.gather(
            bp.pop_paused("contested"),
            bp.pop_paused("contested"),
        )
        non_none = [r for r in results if r is not None]
        assert len(non_none) == 1


class TestBreakpointTimeout:
    async def test_event_wait_with_timeout_fires(self) -> None:
        """Simulates the timeout pattern used in _handle_breakpoint."""
        bp.arm()
        flow = _mock_flow("timeout-flow")
        ir = _make_ir()
        event = await bp.pause(flow, ir, ir)

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(event.wait(), timeout=0.01)

        # Flow should still be poppable after timeout
        pf = await bp.pop_paused("timeout-flow")
        assert pf is not None
        assert pf.dropped is False
