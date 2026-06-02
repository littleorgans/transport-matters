from transport_matters.ir import Message, ToolUseBlock
from transport_matters.test_track_manager_support import (
    CLAUDE_SPAWN_ID,
    ROOT_RUN_ID,
    _request,
    _response,
    _tool_result,
)
from transport_matters.track_manager import TrackManager


def test_classify_request_then_observe_response_matches_record_exchange() -> None:
    request = _request()
    response = _response(
        content=[
            ToolUseBlock(
                id=CLAUDE_SPAWN_ID,
                name="Agent",
                input={"subagent_type": "backend-engineer"},
            )
        ]
    )
    split_manager = TrackManager()
    record_manager = TrackManager()

    split_assignment = split_manager.classify_request(ROOT_RUN_ID, request)
    split_manager.observe_response(ROOT_RUN_ID, split_assignment.track_id, response)
    record_assignment = record_manager.record_exchange(ROOT_RUN_ID, request, response)

    assert split_assignment == record_assignment
    assert split_manager.tracks(ROOT_RUN_ID) == record_manager.tracks(ROOT_RUN_ID)


def test_continuation_does_not_collide_with_parent_tool_results() -> None:
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
    manager.observe_response(
        ROOT_RUN_ID,
        ROOT_RUN_ID,
        _response(
            content=[
                ToolUseBlock(
                    id="toolu_parent_read",
                    name="Read",
                    input={"file_path": "root.py"},
                )
            ]
        ),
    )

    parent_continuation = manager.record_exchange(
        ROOT_RUN_ID,
        _request(
            tools_count=100,
            messages=[
                Message(
                    role="user",
                    content=[_tool_result("toolu_parent_read", "root contents")],
                )
            ],
        ),
        None,
    )

    assert parent_continuation.track_id == ROOT_RUN_ID
    assert parent_continuation.track_role == "parent"
