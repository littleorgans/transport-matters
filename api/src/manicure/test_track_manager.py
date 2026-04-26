from __future__ import annotations

import json

from manicure.ir import (
    InternalRequest,
    InternalResponse,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
    ToolDef,
    ToolResultBlock,
    ToolUseBlock,
    UsageStats,
)
from manicure.track_manager import TrackAssignment, TrackManager

ROOT_RUN_ID = "run-root"
CLAUDE_SPAWN_ID = "toolu_01MiLL7GyXKvFTneZmojAazu"
CODEX_SPAWN_ID = "call_Qp6Z4Fq3ZMJG9TIQJxEoueHB"
CODEX_AGENT_ID = "019dc432-c4bc-75d2-a8e5-be095061139d"


def _tool(name: str) -> ToolDef:
    return ToolDef(name=name, description=name, input_schema={})


def _request(
    *,
    provider: str = "anthropic",
    tools_count: int = 3,
    messages: list[Message] | None = None,
    provider_metadata: dict[str, object] | None = None,
) -> InternalRequest:
    return InternalRequest(
        model="model",
        provider=provider,
        system=[],
        tools=[_tool(f"tool_{index}") for index in range(tools_count)],
        messages=messages or [Message(role="user", content=[TextBlock(text="hi")])],
        sampling=SamplingParams(max_tokens=1024),
        metadata=RequestMetadata(provider_metadata=provider_metadata or {}),
    )


def _response(
    *,
    provider: str = "anthropic",
    content: list[TextBlock | ToolUseBlock] | None = None,
) -> InternalResponse:
    return InternalResponse(
        id="resp",
        model="model",
        provider=provider,
        usage=UsageStats(),
        content=content or [TextBlock(text="ok")],
    )


def _tool_result(tool_use_id: str, text: str) -> ToolResultBlock:
    return ToolResultBlock(
        tool_use_id=tool_use_id,
        content=[TextBlock(text=text)],
    )


def _run_trace(
    manager: TrackManager,
    run_id: str,
    trace: list[tuple[str, InternalRequest, InternalResponse | None]],
) -> dict[str, TrackAssignment]:
    assignments: dict[str, TrackAssignment] = {}
    for exchange_id, request, response in trace:
        assignments[exchange_id] = manager.record_exchange(run_id, request, response)
    return assignments


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

    tracks = manager.tracks(run_id)
    assert set(tracks) == {run_id, CLAUDE_SPAWN_ID}
    assert tracks[CLAUDE_SPAWN_ID].status == "closed"


def test_codex_reference_trace_assigns_subagent_by_agent_id_and_closes_on_wait() -> (
    None
):
    manager = TrackManager()
    run_id = "c8a06661-613f-4363-9a56-a408ae754b90"

    subagent_metadata: dict[str, object] = {
        "x-openai-subagent": "1",
        "x-codex-window-id": f"{CODEX_AGENT_ID}:window",
        "x-codex-subagent-nickname": "Lagrange",
    }
    assignments = _run_trace(
        manager,
        run_id,
        [
            ("20260425T103228Z-44b2c087", _request(provider="codex"), _response()),
            (
                "20260425T103232Z-d5d9c63e",
                _request(provider="codex"),
                _response(
                    provider="codex",
                    content=[
                        ToolUseBlock(
                            id=CODEX_SPAWN_ID,
                            name="spawn_agent",
                            input={"agent_type": "worker"},
                        )
                    ],
                ),
            ),
            (
                "20260425T103234Z-916f6b05",
                _request(
                    provider="codex",
                    messages=[
                        Message(
                            role="user",
                            content=[
                                _tool_result(
                                    CODEX_SPAWN_ID,
                                    json.dumps(
                                        {
                                            "agent_id": CODEX_AGENT_ID,
                                            "nickname": "Lagrange",
                                        }
                                    ),
                                )
                            ],
                        )
                    ],
                ),
                _response(
                    provider="codex",
                    content=[
                        ToolUseBlock(
                            id="call_wait_lagrange",
                            name="wait_agent",
                            input={"targets": [CODEX_AGENT_ID]},
                        )
                    ],
                ),
            ),
            (
                "20260425T103239Z-081e2bf4",
                _request(provider="codex", provider_metadata=subagent_metadata),
                _response(provider="codex"),
            ),
            (
                "20260425T103240Z-14944234",
                _request(provider="codex", provider_metadata=subagent_metadata),
                _response(provider="codex"),
            ),
            (
                "20260425T103247Z-218354e3",
                _request(provider="codex", provider_metadata=subagent_metadata),
                _response(provider="codex"),
            ),
            (
                "20260425T103253Z-56fbb600",
                _request(provider="codex", provider_metadata=subagent_metadata),
                _response(provider="codex"),
            ),
            (
                "20260425T103421Z-e521671f",
                _request(provider="codex", provider_metadata=subagent_metadata),
                _response(provider="codex"),
            ),
            (
                "20260425T103428Z-bae063a9",
                _request(
                    provider="codex",
                    messages=[
                        Message(
                            role="user",
                            content=[
                                _tool_result(
                                    "call_wait_lagrange",
                                    json.dumps(
                                        {
                                            "status": {CODEX_AGENT_ID: "completed"},
                                        }
                                    ),
                                )
                            ],
                        )
                    ],
                ),
                _response(provider="codex"),
            ),
        ],
    )

    assert assignments["20260425T103228Z-44b2c087"].track_id == run_id
    assert assignments["20260425T103232Z-d5d9c63e"].track_id == run_id
    assert assignments["20260425T103234Z-916f6b05"].track_id == run_id

    subagent_turns = [
        "20260425T103239Z-081e2bf4",
        "20260425T103240Z-14944234",
        "20260425T103247Z-218354e3",
        "20260425T103253Z-56fbb600",
        "20260425T103421Z-e521671f",
    ]
    for turn in subagent_turns:
        assert assignments[turn].track_id == CODEX_AGENT_ID
        assert assignments[turn].parent_track_id == run_id
        assert assignments[turn].track_role == "subagent"
        assert assignments[turn].track_display_name == "Lagrange"

    tracks = manager.tracks(run_id)
    assert set(tracks) == {run_id, CODEX_AGENT_ID}
    assert tracks[CODEX_AGENT_ID].status == "closed"


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

    root_assignment = manager.record_exchange(ROOT_RUN_ID, root_request, root_response)
    child_a = manager.record_exchange(ROOT_RUN_ID, _request(tools_count=90), None)
    child_b = manager.record_exchange(ROOT_RUN_ID, _request(tools_count=90), None)

    assert root_assignment.track_id == ROOT_RUN_ID
    assert child_a.track_id == "toolu_child_a"
    assert child_a.track_display_name == "research"
    assert child_b.track_id == "toolu_child_b"
    assert child_b.track_display_name == "review"
    assert manager.tracks(ROOT_RUN_ID)["toolu_child_a"].status == "open"
    assert manager.tracks(ROOT_RUN_ID)["toolu_child_b"].status == "open"


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


def test_codex_fan_out_continuation_routes_to_correct_subagent() -> None:
    manager = TrackManager()
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(provider="codex", tools_count=100),
        _response(
            provider="codex",
            content=[
                ToolUseBlock(
                    id="call_spawn_a",
                    name="spawn_agent",
                    input={"agent_type": "Explore"},
                ),
                ToolUseBlock(
                    id="call_spawn_b",
                    name="spawn_agent",
                    input={"agent_type": "Explore"},
                ),
            ],
        ),
    )
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(
            provider="codex",
            messages=[
                Message(
                    role="user",
                    content=[
                        _tool_result(
                            "call_spawn_a",
                            json.dumps({"agent_id": "agent_a", "nickname": "Explore"}),
                        ),
                        _tool_result(
                            "call_spawn_b",
                            json.dumps({"agent_id": "agent_b", "nickname": "Explore"}),
                        ),
                    ],
                )
            ],
        ),
        None,
    )
    child_a = manager.record_exchange(
        ROOT_RUN_ID, _request(provider="codex", tools_count=90), None
    )
    child_b = manager.record_exchange(
        ROOT_RUN_ID, _request(provider="codex", tools_count=90), None
    )
    manager.observe_response(
        ROOT_RUN_ID,
        child_a.track_id,
        _response(
            provider="codex",
            content=[
                ToolUseBlock(
                    id="call_child_a_read",
                    name="read_file",
                    input={"path": "a.py"},
                )
            ],
        ),
    )
    manager.observe_response(
        ROOT_RUN_ID,
        child_b.track_id,
        _response(
            provider="codex",
            content=[
                ToolUseBlock(
                    id="call_child_b_read",
                    name="read_file",
                    input={"path": "b.py"},
                )
            ],
        ),
    )

    continuation_a = manager.record_exchange(
        ROOT_RUN_ID,
        _request(
            provider="codex",
            tools_count=90,
            messages=[
                Message(
                    role="user",
                    content=[_tool_result("call_child_a_read", "a contents")],
                )
            ],
        ),
        None,
    )
    continuation_b = manager.record_exchange(
        ROOT_RUN_ID,
        _request(
            provider="codex",
            tools_count=90,
            messages=[
                Message(
                    role="user",
                    content=[_tool_result("call_child_b_read", "b contents")],
                )
            ],
        ),
        None,
    )

    assert child_a.track_id == "agent_a"
    assert child_b.track_id == "agent_b"
    assert continuation_a.track_id == "agent_a"
    assert continuation_a.track_role == "subagent"
    assert continuation_b.track_id == "agent_b"
    assert continuation_b.track_role == "subagent"


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


def test_late_tool_result_for_closed_subagent_falls_back_to_parent() -> None:
    manager = TrackManager()
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(tools_count=100),
        _response(
            content=[
                ToolUseBlock(
                    id="toolu_child",
                    name="Agent",
                    input={"subagent_type": "Explore"},
                )
            ]
        ),
    )
    child = manager.record_exchange(ROOT_RUN_ID, _request(tools_count=90), None)
    manager.observe_response(
        ROOT_RUN_ID,
        child.track_id,
        _response(
            content=[
                ToolUseBlock(
                    id="toolu_child_read",
                    name="Read",
                    input={"file_path": "a.py"},
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
                    id="toolu_parent_kill",
                    name="agent_kill",
                    input={"target": child.track_id},
                )
            ]
        ),
    )

    late_result = manager.record_exchange(
        ROOT_RUN_ID,
        _request(
            tools_count=90,
            messages=[
                Message(
                    role="user",
                    content=[_tool_result("toolu_child_read", "late contents")],
                )
            ],
        ),
        None,
    )

    assert manager.tracks(ROOT_RUN_ID)[child.track_id].status == "closed"
    assert late_result.track_id == ROOT_RUN_ID
    assert late_result.track_role == "parent"


def test_late_tool_result_for_closed_subagent_does_not_match_sibling_signature() -> (
    None
):
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
        ROOT_RUN_ID,
        _response(
            content=[
                ToolUseBlock(
                    id="toolu_parent_kill",
                    name="agent_kill",
                    input={"target": child_a.track_id},
                )
            ]
        ),
    )

    late_result = manager.record_exchange(
        ROOT_RUN_ID,
        _request(
            tools_count=90,
            messages=[
                Message(
                    role="user",
                    content=[_tool_result("toolu_child_a_read", "late contents")],
                )
            ],
        ),
        None,
    )

    assert child_a.track_id == "toolu_child_a"
    assert child_b.track_id == "toolu_child_b"
    assert manager.tracks(ROOT_RUN_ID)["toolu_child_a"].status == "closed"
    assert manager.tracks(ROOT_RUN_ID)["toolu_child_b"].status == "open"
    assert late_result.track_id == ROOT_RUN_ID
    assert late_result.track_role == "parent"


def test_codex_agent_kill_closes_targeted_subagent_track() -> None:
    manager = TrackManager()
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(provider="codex"),
        _response(
            provider="codex",
            content=[
                ToolUseBlock(
                    id=CODEX_SPAWN_ID,
                    name="spawn_agent",
                    input={"agent_type": "worker"},
                )
            ],
        ),
    )
    spawn_result_request = _request(
        provider="codex",
        messages=[
            Message(
                role="user",
                content=[
                    _tool_result(
                        CODEX_SPAWN_ID,
                        json.dumps({"agent_id": CODEX_AGENT_ID, "nickname": "worker"}),
                    )
                ],
            )
        ],
    )
    manager.record_exchange(ROOT_RUN_ID, spawn_result_request, None)

    manager.record_exchange(
        ROOT_RUN_ID,
        _request(provider="codex"),
        _response(
            provider="codex",
            content=[
                ToolUseBlock(
                    id="call_kill",
                    name="agent_kill",
                    input={"target": CODEX_AGENT_ID},
                )
            ],
        ),
    )

    assert manager.tracks(ROOT_RUN_ID)[CODEX_AGENT_ID].status == "closed"


def test_codex_resolved_spawn_result_does_not_reopen_closed_track() -> None:
    manager = TrackManager()
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(provider="codex"),
        _response(
            provider="codex",
            content=[
                ToolUseBlock(
                    id=CODEX_SPAWN_ID,
                    name="spawn_agent",
                    input={"agent_type": "worker"},
                )
            ],
        ),
    )
    spawn_result_request = _request(
        provider="codex",
        messages=[
            Message(
                role="user",
                content=[
                    _tool_result(
                        CODEX_SPAWN_ID,
                        json.dumps({"agent_id": CODEX_AGENT_ID, "nickname": "worker"}),
                    )
                ],
            )
        ],
    )
    manager.record_exchange(ROOT_RUN_ID, spawn_result_request, None)
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(provider="codex"),
        _response(
            provider="codex",
            content=[
                ToolUseBlock(
                    id="call_kill",
                    name="agent_kill",
                    input={"target": CODEX_AGENT_ID},
                )
            ],
        ),
    )

    manager.record_exchange(ROOT_RUN_ID, spawn_result_request, None)

    assert manager.tracks(ROOT_RUN_ID)[CODEX_AGENT_ID].status == "closed"


def test_codex_subagent_name_can_come_from_turn_metadata() -> None:
    manager = TrackManager()
    assignment = manager.record_exchange(
        ROOT_RUN_ID,
        _request(
            provider="codex",
            provider_metadata={
                "x-openai-subagent": "1",
                "x-codex-window-id": f"{CODEX_AGENT_ID}:0",
                "x-codex-turn-metadata": json.dumps(
                    {
                        "session_id": CODEX_AGENT_ID,
                        "thread_source": "subagent",
                        "subagent_nickname": "Mendel",
                    }
                ),
            },
        ),
        None,
    )

    assert assignment.track_id == CODEX_AGENT_ID
    assert assignment.track_display_name == "Mendel"


def test_nested_subagent_track_records_parent_track_id() -> None:
    manager = TrackManager()
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(tools_count=100),
        _response(
            content=[
                ToolUseBlock(
                    id="toolu_child",
                    name="Agent",
                    input={"subagent_type": "worker"},
                )
            ]
        ),
    )
    child_assignment = manager.record_exchange(
        ROOT_RUN_ID, _request(tools_count=90), None
    )
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(tools_count=90),
        _response(
            content=[
                ToolUseBlock(
                    id="toolu_grandchild",
                    name="Agent",
                    input={"subagent_type": "nested"},
                )
            ]
        ),
    )
    grandchild_assignment = manager.record_exchange(
        ROOT_RUN_ID, _request(tools_count=80), None
    )

    assert child_assignment.track_id == "toolu_child"
    assert grandchild_assignment.track_id == "toolu_grandchild"
    assert grandchild_assignment.parent_track_id == "toolu_child"


def test_codex_failed_spawn_result_does_not_open_track() -> None:
    manager = TrackManager()
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(provider="codex"),
        _response(
            provider="codex",
            content=[
                ToolUseBlock(
                    id="call_failed",
                    name="spawn_agent",
                    input={"message": "bad spawn"},
                )
            ],
        ),
    )
    result_request = _request(
        provider="codex",
        messages=[
            Message(
                role="user",
                content=[
                    _tool_result("call_failed", json.dumps({"error": "rejected"}))
                ],
            )
        ],
    )

    assignment = manager.record_exchange(ROOT_RUN_ID, result_request, None)

    assert assignment.track_id == ROOT_RUN_ID
    assert set(manager.tracks(ROOT_RUN_ID)) == {ROOT_RUN_ID}
