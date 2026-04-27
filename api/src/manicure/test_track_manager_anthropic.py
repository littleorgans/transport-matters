from __future__ import annotations

from manicure.ir import Message, ToolUseBlock
from manicure.test_track_manager_support import (
    CLAUDE_SPAWN_ID,
    ROOT_RUN_ID,
    _request,
    _response,
    _run_trace,
    _tool_result,
)
from manicure.track_manager import TrackManager


def test_anthropic_reference_trace_assigns_parent_and_subagent_tracks() -> None:
    manager = TrackManager()
    run_id = "30f11302-7270-4d81-a054-721ffac87aae"

    assignments = _run_trace(
        manager,
        run_id,
        [
            (
                "20260425T093009Z-f3495083",
                _request(tools_count=100),
                _response(
                    content=[
                        ToolUseBlock(
                            id=CLAUDE_SPAWN_ID,
                            name="Agent",
                            input={"subagent_type": "helioy-tools:deep-research"},
                        )
                    ]
                ),
            ),
            ("20260425T093014Z-75414f56", _request(tools_count=90), _response()),
            ("20260425T093037Z-93f366bf", _request(tools_count=90), _response()),
            ("20260425T093054Z-ae064ac4", _request(tools_count=90), _response()),
            ("20260425T093105Z-bda4fbf7", _request(tools_count=90), _response()),
            ("20260425T093146Z-1729f167", _request(tools_count=90), _response()),
            (
                "20260425T093156Z-c0996e30",
                _request(
                    messages=[
                        Message(
                            role="user",
                            content=[_tool_result(CLAUDE_SPAWN_ID, "completed")],
                        )
                    ]
                ),
                _response(),
            ),
            ("20260425T093459Z-7f52f720", _request(), _response()),
        ],
    )

    parent_turns = [
        "20260425T093009Z-f3495083",
        "20260425T093156Z-c0996e30",
        "20260425T093459Z-7f52f720",
    ]
    subagent_turns = [
        "20260425T093014Z-75414f56",
        "20260425T093037Z-93f366bf",
        "20260425T093054Z-ae064ac4",
        "20260425T093105Z-bda4fbf7",
        "20260425T093146Z-1729f167",
    ]

    for turn in parent_turns:
        assert assignments[turn].track_id == run_id
        assert assignments[turn].track_role == "parent"

    for turn in subagent_turns:
        assert assignments[turn].track_id == CLAUDE_SPAWN_ID
        assert assignments[turn].parent_track_id == run_id
        assert assignments[turn].track_role == "subagent"
        assert assignments[turn].track_display_name == "helioy-tools:deep-research"
        assert assignments[turn].track_spawn_exchange_id == "20260425T093009Z-f3495083"
        assert assignments[turn].track_spawn_tool_use_id == CLAUDE_SPAWN_ID
        assert assignments[turn].track_spawn_order == 0

    tracks = manager.tracks(run_id)
    assert set(tracks) == {run_id, CLAUDE_SPAWN_ID}
    assert tracks[CLAUDE_SPAWN_ID].status == "closed"


def test_anthropic_fan_out_keeps_two_concurrent_subagent_tracks_open() -> None:
    manager = TrackManager()
    root_request = _request(tools_count=100)
    root_response = _response(
        content=[
            ToolUseBlock(
                id="toolu_child_a",
                name="Agent",
                input={"subagent_type": "research"},
            ),
            ToolUseBlock(
                id="toolu_child_b",
                name="Agent",
                input={"subagent_type": "review"},
            ),
        ]
    )

    root_assignment = manager.record_exchange(
        ROOT_RUN_ID, root_request, root_response, exchange_id="ex-anthropic-fanout"
    )
    child_a = manager.record_exchange(ROOT_RUN_ID, _request(tools_count=90), None)
    child_b = manager.record_exchange(ROOT_RUN_ID, _request(tools_count=90), None)

    assert root_assignment.track_id == ROOT_RUN_ID
    assert child_a.track_id == "toolu_child_a"
    assert child_a.track_display_name == "research"
    assert child_a.track_spawn_exchange_id == "ex-anthropic-fanout"
    assert child_a.track_spawn_tool_use_id == "toolu_child_a"
    assert child_a.track_spawn_order == 0
    assert child_b.track_id == "toolu_child_b"
    assert child_b.track_display_name == "review"
    assert child_b.track_spawn_exchange_id == "ex-anthropic-fanout"
    assert child_b.track_spawn_tool_use_id == "toolu_child_b"
    assert child_b.track_spawn_order == 1
    assert manager.tracks(ROOT_RUN_ID)["toolu_child_a"].status == "open"
    assert manager.tracks(ROOT_RUN_ID)["toolu_child_b"].status == "open"


def test_anthropic_spawn_order_ignores_non_spawn_tool_uses() -> None:
    manager = TrackManager()
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(tools_count=100),
        _response(
            content=[
                ToolUseBlock(id="toolu_read", name="Read", input={"file_path": "x"}),
                ToolUseBlock(
                    id="toolu_child_a",
                    name="Agent",
                    input={"subagent_type": "Explore"},
                ),
                ToolUseBlock(
                    id="toolu_wait",
                    name="wait_agent",
                    input={"targets": ["toolu_child_a"]},
                ),
                ToolUseBlock(
                    id="toolu_child_b",
                    name="Agent",
                    input={"subagent_type": "Explore"},
                ),
            ],
        ),
        exchange_id="ex-spawn-root",
    )

    child_a = manager.record_exchange(ROOT_RUN_ID, _request(tools_count=90), None)
    child_b = manager.record_exchange(ROOT_RUN_ID, _request(tools_count=90), None)

    assert child_a.track_id == "toolu_child_a"
    assert child_a.track_spawn_exchange_id == "ex-spawn-root"
    assert child_a.track_spawn_tool_use_id == "toolu_child_a"
    assert child_a.track_spawn_order == 0
    assert child_b.track_id == "toolu_child_b"
    assert child_b.track_spawn_exchange_id == "ex-spawn-root"
    assert child_b.track_spawn_tool_use_id == "toolu_child_b"
    assert child_b.track_spawn_order == 1


def test_anthropic_fan_out_continuation_routes_to_correct_subagent() -> None:
    manager = TrackManager()
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(tools_count=100),
        _response(
            content=[
                ToolUseBlock(
                    id="toolu_child_a",
                    name="Agent",
                    input={"subagent_type": "Explore"},
                ),
                ToolUseBlock(
                    id="toolu_child_b",
                    name="Agent",
                    input={"subagent_type": "Explore"},
                ),
            ]
        ),
    )
    child_a = manager.record_exchange(ROOT_RUN_ID, _request(tools_count=90), None)
    child_b = manager.record_exchange(ROOT_RUN_ID, _request(tools_count=90), None)
    manager.observe_response(
        ROOT_RUN_ID,
        child_a.track_id,
        _response(
            content=[
                ToolUseBlock(
                    id="toolu_child_a_read",
                    name="Read",
                    input={"file_path": "a.py"},
                )
            ]
        ),
    )
    manager.observe_response(
        ROOT_RUN_ID,
        child_b.track_id,
        _response(
            content=[
                ToolUseBlock(
                    id="toolu_child_b_read",
                    name="Read",
                    input={"file_path": "b.py"},
                )
            ]
        ),
    )

    continuation_a = manager.record_exchange(
        ROOT_RUN_ID,
        _request(
            tools_count=90,
            messages=[
                Message(
                    role="user",
                    content=[_tool_result("toolu_child_a_read", "a contents")],
                )
            ],
        ),
        None,
    )
    continuation_b = manager.record_exchange(
        ROOT_RUN_ID,
        _request(
            tools_count=90,
            messages=[
                Message(
                    role="user",
                    content=[_tool_result("toolu_child_b_read", "b contents")],
                )
            ],
        ),
        None,
    )

    assert child_a.track_id == "toolu_child_a"
    assert child_b.track_id == "toolu_child_b"
    assert continuation_a.track_id == "toolu_child_a"
    assert continuation_a.track_role == "subagent"
    assert continuation_b.track_id == "toolu_child_b"
    assert continuation_b.track_role == "subagent"
