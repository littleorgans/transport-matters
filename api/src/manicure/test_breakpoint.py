"""Tests for the breakpoint state machine."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from manicure import breakpoint as bp
from manicure.ir import (
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


class TestPause:
    def test_pause_stays_armed_and_registers(self) -> None:
        bp.arm()
        flow = _mock_flow()
        ir = _make_ir()

        event = bp.pause(flow, ir)

        assert bp.get_mode() == "armed_once"
        assert "flow-001" in bp.get_paused()
        assert not event.is_set()

        pf = bp.get_paused()["flow-001"]
        assert pf.curated_ir is ir
        assert pf.flow is flow
        assert pf.paused_at_ms > 0


class TestRelease:
    def test_release_sets_event(self) -> None:
        bp.arm()
        flow = _mock_flow()
        ir = _make_ir()
        event = bp.pause(flow, ir)

        mutated = _make_ir()
        ok = bp.release("flow-001", mutated)

        assert ok is True
        assert event.is_set()
        pf = bp.get_paused()["flow-001"]
        assert pf.mutated_ir is mutated
        assert pf.dropped is False

    def test_release_unknown_returns_false(self) -> None:
        assert bp.release("nonexistent", _make_ir()) is False


class TestDrop:
    def test_drop_sets_event(self) -> None:
        bp.arm()
        flow = _mock_flow()
        ir = _make_ir()
        event = bp.pause(flow, ir)

        ok = bp.drop("flow-001")

        assert ok is True
        assert event.is_set()
        pf = bp.get_paused()["flow-001"]
        assert pf.dropped is True

    def test_drop_unknown_returns_false(self) -> None:
        assert bp.drop("nonexistent") is False


class TestClearAll:
    def test_clear_all(self) -> None:
        bp.arm()
        flow1 = _mock_flow("f1")
        flow2 = _mock_flow("f2")
        ir = _make_ir()

        bp.pause(flow1, ir)
        # Re-arm for second pause
        bp.arm()
        bp.pause(flow2, ir)

        assert len(bp.get_paused()) == 2

        bp.clear_all()

        # All flows should be marked dropped with events set
        for pf in bp.get_paused().values():
            assert pf.dropped is True
            assert pf.event.is_set()
