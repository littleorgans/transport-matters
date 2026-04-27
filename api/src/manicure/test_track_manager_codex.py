from __future__ import annotations

import json

from manicure.ir import Message, ToolUseBlock
from manicure.test_track_manager_support import (
    CODEX_AGENT_ID,
    CODEX_SPAWN_ID,
    ROOT_RUN_ID,
    _request,
    _response,
    _run_trace,
    _tool_result,
)
from manicure.track_manager import TrackManager


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
        assert assignments[turn].track_spawn_exchange_id == "20260425T103232Z-d5d9c63e"
        assert assignments[turn].track_spawn_tool_use_id == CODEX_SPAWN_ID
        assert assignments[turn].track_spawn_order == 0

    tracks = manager.tracks(run_id)
    assert set(tracks) == {run_id, CODEX_AGENT_ID}
    assert tracks[CODEX_AGENT_ID].status == "closed"


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
        exchange_id="ex-codex-fanout",
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
    assert child_a.track_spawn_exchange_id == "ex-codex-fanout"
    assert child_a.track_spawn_tool_use_id == "call_spawn_a"
    assert child_a.track_spawn_order == 0
    assert child_b.track_id == "agent_b"
    assert child_b.track_spawn_exchange_id == "ex-codex-fanout"
    assert child_b.track_spawn_tool_use_id == "call_spawn_b"
    assert child_b.track_spawn_order == 1
    assert continuation_a.track_id == "agent_a"
    assert continuation_a.track_role == "subagent"
    assert continuation_a.track_spawn_exchange_id == "ex-codex-fanout"
    assert continuation_a.track_spawn_tool_use_id == "call_spawn_a"
    assert continuation_a.track_spawn_order == 0
    assert continuation_b.track_id == "agent_b"
    assert continuation_b.track_role == "subagent"
    assert continuation_b.track_spawn_exchange_id == "ex-codex-fanout"
    assert continuation_b.track_spawn_tool_use_id == "call_spawn_b"
    assert continuation_b.track_spawn_order == 1
