import json
from datetime import UTC, datetime

from transport_matters import broadcast
from transport_matters.addon import build_req_stats, emit_exchange
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from transport_matters.storage.base import (
    CodexTurnListSummary,
    PipelineStats,
    SpawnAnchor,
)


def _make_ir() -> InternalRequest:
    return InternalRequest(
        model="claude-3",
        provider="anthropic",
        system=[],
        tools=[],
        messages=[Message(role="user", content=[TextBlock(text="hello")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(),
    )


class TestEmitExchange:
    """emit_exchange SSE payload includes exchange metadata fields."""

    def setup_method(self) -> None:
        broadcast._subscribers.clear()
        broadcast._next_id = 0

    def teardown_method(self) -> None:
        broadcast._subscribers.clear()
        broadcast._next_id = 0

    def test_payload_includes_mutated_manually_and_pipeline(self) -> None:
        ir = _make_ir()
        req_stats = build_req_stats(ir)
        pipeline_stats = PipelineStats(
            overrides_applied=[],
            chars_before=100,
            chars_after=80,
            tokens_before=60,
            tokens_after=50,
        )
        q = broadcast.subscribe()

        emit_exchange(
            ir,
            req_stats,
            None,
            "exchange-1",
            datetime(2026, 1, 1, tzinfo=UTC),
            None,
            mutated_manually=True,
            pipeline_stats=pipeline_stats,
        )

        assert not q.empty()
        data = json.loads(q.get_nowait())
        assert data["mutated_manually"] is True
        assert data["pipeline"]["chars_before"] == 100
        assert data["pipeline"]["chars_after"] == 80

    def test_payload_includes_flow_id_when_provided(self) -> None:
        ir = _make_ir()
        req_stats = build_req_stats(ir)
        q = broadcast.subscribe()

        emit_exchange(
            ir,
            req_stats,
            None,
            "exchange-3",
            datetime(2026, 1, 1, tzinfo=UTC),
            None,
            flow_id="mitmproxy-flow-abc123",
        )

        data = json.loads(q.get_nowait())
        assert data["flow_id"] == "mitmproxy-flow-abc123"

    def test_payload_includes_codex_turn_when_provided(self) -> None:
        ir = _make_ir().model_copy(update={"provider": "codex", "model": "codex/gpt-5-codex"})
        req_stats = build_req_stats(ir)
        q = broadcast.subscribe()

        emit_exchange(
            ir,
            req_stats,
            None,
            "exchange-codex-1",
            datetime(2026, 1, 1, tzinfo=UTC),
            None,
            codex_turn=CodexTurnListSummary(
                turn_index=2,
                message_range_start=4,
                message_range_end=7,
                status="completed",
                terminal_cause="response_completed",
                stop_reason="completed",
                text_chars=321,
                tool_calls=2,
            ),
        )

        data = json.loads(q.get_nowait())
        assert data["codex_turn"] == {
            "turn_index": 2,
            "message_range_start": 4,
            "message_range_end": 7,
            "status": "completed",
            "terminal_cause": "response_completed",
            "stop_reason": "completed",
            "text_chars": 321,
            "tool_calls": 2,
        }

    def test_payload_omits_flow_id_when_none(self) -> None:
        ir = _make_ir()
        req_stats = build_req_stats(ir)
        q = broadcast.subscribe()

        emit_exchange(
            ir,
            req_stats,
            None,
            "exchange-4",
            datetime(2026, 1, 1, tzinfo=UTC),
            None,
        )

        data = json.loads(q.get_nowait())
        assert "flow_id" not in data

    def test_payload_includes_spawn_anchor_object(self) -> None:
        ir = _make_ir()
        req_stats = build_req_stats(ir)
        q = broadcast.subscribe()

        emit_exchange(
            ir,
            req_stats,
            None,
            "exchange-anchor",
            datetime(2026, 1, 1, tzinfo=UTC),
            None,
            spawn_anchor=SpawnAnchor(
                track_spawn_exchange_id="ex-parent",
                track_spawn_tool_use_id="toolu_child",
                track_spawn_order=1,
            ),
        )

        data = json.loads(q.get_nowait())
        assert data["spawn_anchor"] == {
            "track_spawn_exchange_id": "ex-parent",
            "track_spawn_tool_use_id": "toolu_child",
            "track_spawn_order": 1,
        }
        assert "track_spawn_exchange_id" not in data
        assert "track_spawn_tool_use_id" not in data
        assert "track_spawn_order" not in data

    def test_payload_defaults_spawn_anchor_to_none(self) -> None:
        ir = _make_ir()
        req_stats = build_req_stats(ir)
        q = broadcast.subscribe()

        emit_exchange(
            ir,
            req_stats,
            None,
            "exchange-anchor-default",
            datetime(2026, 1, 1, tzinfo=UTC),
            None,
        )

        data = json.loads(q.get_nowait())
        assert data["spawn_anchor"] is None

    def test_defaults_omit_pipeline_and_mutated_false(self) -> None:
        ir = _make_ir()
        req_stats = build_req_stats(ir)
        q = broadcast.subscribe()

        emit_exchange(ir, req_stats, None, "exchange-2", datetime(2026, 1, 1, tzinfo=UTC), None)

        assert not q.empty()
        data = json.loads(q.get_nowait())
        assert data["mutated_manually"] is False
        assert data["pipeline"] is None
