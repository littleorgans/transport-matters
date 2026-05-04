from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from transport_matters.ir import InternalRequest, Message, ToolUseBlock
from transport_matters.test_track_manager_support import (
    CODEX_AGENT_ID,
    CODEX_SPAWN_ID,
    ROOT_RUN_ID,
    _request,
    _response,
    _tool_result,
)
from transport_matters.track_manager import TrackAssignment, TrackManager

if TYPE_CHECKING:
    from collections.abc import Callable

CaseAssignments = dict[str, TrackAssignment]


@dataclass(frozen=True)
class ExpectedAnchor:
    assignment_key: str
    track_id: str
    parent_track_id: str | None
    exchange_id: str | None
    tool_use_id: str | None
    order: int | None
    display_name: str | None = None


@dataclass(frozen=True)
class AnchorCase:
    name: str
    arrange: Callable[[TrackManager], CaseAssignments]
    expected: tuple[ExpectedAnchor, ...]
    assert_case: Callable[[TrackManager, CaseAssignments], None] | None = None


def _agent_tool_use(tool_use_id: str, subagent_type: str = "Explore") -> ToolUseBlock:
    return ToolUseBlock(
        id=tool_use_id,
        name="Agent",
        input={"subagent_type": subagent_type},
    )


def _codex_spawn_tool_use(
    tool_use_id: str = CODEX_SPAWN_ID, agent_type: str = "worker"
) -> ToolUseBlock:
    return ToolUseBlock(
        id=tool_use_id,
        name="spawn_agent",
        input={"agent_type": agent_type},
    )


def _codex_spawn_result_request(
    spawn_id: str = CODEX_SPAWN_ID,
    *,
    agent_id: str = CODEX_AGENT_ID,
    nickname: str = "worker",
) -> InternalRequest:
    return _request(
        provider="codex",
        messages=[
            Message(
                role="user",
                content=[
                    _tool_result(
                        spawn_id,
                        json.dumps({"agent_id": agent_id, "nickname": nickname}),
                    )
                ],
            )
        ],
    )


def _assignment_for_track(manager: TrackManager, track_id: str) -> TrackAssignment:
    return manager._assignment(manager._state(ROOT_RUN_ID), track_id)


def _spawn_anthropic_children(
    manager: TrackManager, *spawn_ids: str
) -> dict[str, TrackAssignment]:
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(tools_count=100),
        _response(content=[_agent_tool_use(spawn_id) for spawn_id in spawn_ids]),
    )
    return {
        spawn_id: manager.record_exchange(ROOT_RUN_ID, _request(tools_count=90), None)
        for spawn_id in spawn_ids
    }


def _record_child_tool_use(
    manager: TrackManager, child_track_id: str, tool_use_id: str
) -> None:
    manager.observe_response(
        ROOT_RUN_ID,
        child_track_id,
        _response(
            content=[
                ToolUseBlock(
                    id=tool_use_id,
                    name="Read",
                    input={"file_path": "a.py"},
                )
            ]
        ),
    )


def _kill_track(manager: TrackManager, track_id: str) -> None:
    manager.observe_response(
        ROOT_RUN_ID,
        ROOT_RUN_ID,
        _response(
            content=[
                ToolUseBlock(
                    id="toolu_parent_kill",
                    name="agent_kill",
                    input={"target": track_id},
                )
            ]
        ),
    )


def _late_tool_result_request(tool_use_id: str) -> InternalRequest:
    return _request(
        tools_count=90,
        messages=[
            Message(
                role="user",
                content=[_tool_result(tool_use_id, "late contents")],
            )
        ],
    )


@pytest.mark.parametrize(
    (
        "spawn_ids",
        "tool_owner_spawn_id",
        "tool_use_id",
        "expected_statuses",
    ),
    (
        pytest.param(
            ("toolu_child",),
            "toolu_child",
            "toolu_child_read",
            {"toolu_child": "closed"},
            id="test_late_tool_result_for_closed_subagent_falls_back_to_parent",
        ),
        pytest.param(
            ("toolu_child_a", "toolu_child_b"),
            "toolu_child_a",
            "toolu_child_a_read",
            {"toolu_child_a": "closed", "toolu_child_b": "open"},
            id="test_late_tool_result_for_closed_subagent_does_not_match_sibling_signature",
        ),
    ),
)
def test_late_tool_result_for_closed_subagent_routes_to_parent(
    spawn_ids: tuple[str, ...],
    tool_owner_spawn_id: str,
    tool_use_id: str,
    expected_statuses: dict[str, str],
) -> None:
    manager = TrackManager()
    children = _spawn_anthropic_children(manager, *spawn_ids)
    tool_owner = children[tool_owner_spawn_id]
    _record_child_tool_use(manager, tool_owner.track_id, tool_use_id)
    _kill_track(manager, tool_owner.track_id)

    late_result = manager.record_exchange(
        ROOT_RUN_ID, _late_tool_result_request(tool_use_id), None
    )

    for track_id, expected_status in expected_statuses.items():
        assert children[track_id].track_id == track_id
        assert manager.tracks(ROOT_RUN_ID)[track_id].status == expected_status
    assert late_result.track_id == ROOT_RUN_ID
    assert late_result.track_role == "parent"


def test_codex_agent_kill_closes_targeted_subagent_track() -> None:
    manager = TrackManager()
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(provider="codex"),
        _response(provider="codex", content=[_codex_spawn_tool_use()]),
    )
    manager.record_exchange(ROOT_RUN_ID, _codex_spawn_result_request(), None)
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
        _response(provider="codex", content=[_codex_spawn_tool_use()]),
    )
    spawn_result_request = _codex_spawn_result_request()
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


def _arrange_codex_turn_metadata_name(
    manager: TrackManager,
) -> CaseAssignments:
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
    return {"assignment": assignment}


def _arrange_nested_anthropic_subagent(
    manager: TrackManager,
) -> CaseAssignments:
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(tools_count=100),
        _response(content=[_agent_tool_use("toolu_child", "worker")]),
        exchange_id="ex-root-spawn",
    )
    child_assignment = manager.record_exchange(
        ROOT_RUN_ID, _request(tools_count=90), None
    )
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(tools_count=90),
        _response(content=[_agent_tool_use("toolu_grandchild", "nested")]),
        exchange_id="ex-child-spawn",
    )
    grandchild_assignment = manager.record_exchange(
        ROOT_RUN_ID, _request(tools_count=80), None
    )
    return {"child": child_assignment, "grandchild": grandchild_assignment}


def _arrange_anthropic_closure_preserves_spawn_anchor(
    manager: TrackManager,
) -> CaseAssignments:
    spawn_id = "toolu_close_anchor"
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(tools_count=100),
        _response(content=[_agent_tool_use(spawn_id, "research")]),
        exchange_id="ex-anthropic-spawn",
    )
    manager.record_exchange(ROOT_RUN_ID, _request(tools_count=90), None)
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(
            tools_count=100,
            messages=[
                Message(
                    role="user",
                    content=[_tool_result(spawn_id, "completed")],
                )
            ],
        ),
        None,
    )
    return {"closed": _assignment_for_track(manager, spawn_id)}


def _arrange_codex_nested_subagent(
    manager: TrackManager,
) -> CaseAssignments:
    grandchild_id = "019dc432-c4bc-75d2-a8e5-fffffffffff1"
    manager.record_exchange(
        ROOT_RUN_ID,
        _request(provider="codex", tools_count=100),
        _response(provider="codex", content=[_codex_spawn_tool_use()]),
        exchange_id="ex-root-spawn",
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
                            CODEX_SPAWN_ID,
                            json.dumps(
                                {"agent_id": CODEX_AGENT_ID, "nickname": "worker"}
                            ),
                        )
                    ],
                )
            ],
        ),
        None,
    )
    child_metadata: dict[str, object] = {
        "x-openai-subagent": "1",
        "x-codex-window-id": f"{CODEX_AGENT_ID}:0",
    }
    child_assignment = manager.record_exchange(
        ROOT_RUN_ID,
        _request(provider="codex", tools_count=90, provider_metadata=child_metadata),
        _response(
            provider="codex",
            content=[
                ToolUseBlock(
                    id="call_grandchild_spawn",
                    name="spawn_agent",
                    input={"agent_type": "nested"},
                )
            ],
        ),
        exchange_id="ex-child-spawn",
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
                            "call_grandchild_spawn",
                            json.dumps(
                                {"agent_id": grandchild_id, "nickname": "nested"}
                            ),
                        )
                    ],
                )
            ],
        ),
        None,
    )
    grandchild_assignment = manager.record_exchange(
        ROOT_RUN_ID,
        _request(
            provider="codex",
            tools_count=80,
            provider_metadata={
                "x-openai-subagent": "1",
                "x-codex-window-id": f"{grandchild_id}:0",
            },
        ),
        None,
    )
    return {"child": child_assignment, "grandchild": grandchild_assignment}


def _arrange_codex_failed_spawn_result(
    manager: TrackManager,
) -> CaseAssignments:
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
        exchange_id="ex-failed-spawn",
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
    return {
        "assignment": assignment,
        "parent": _assignment_for_track(manager, ROOT_RUN_ID),
    }


def _assert_codex_failed_spawn(
    manager: TrackManager, assignments: CaseAssignments
) -> None:
    assert assignments["assignment"].track_id == ROOT_RUN_ID
    assert set(manager.tracks(ROOT_RUN_ID)) == {ROOT_RUN_ID}
    assert manager._runs[ROOT_RUN_ID].open_spawns == {}


def _assert_anthropic_closed_spawn_anchor(
    manager: TrackManager, assignments: CaseAssignments
) -> None:
    assert assignments["closed"].track_id == "toolu_close_anchor"
    assert manager.tracks(ROOT_RUN_ID)["toolu_close_anchor"].status == "closed"


ANCHOR_CASES: tuple[AnchorCase, ...] = (
    AnchorCase(
        "test_codex_subagent_name_can_come_from_turn_metadata",
        _arrange_codex_turn_metadata_name,
        (
            ExpectedAnchor(
                "assignment",
                CODEX_AGENT_ID,
                ROOT_RUN_ID,
                None,
                None,
                None,
                "Mendel",
            ),
        ),
    ),
    AnchorCase(
        "test_nested_subagent_track_records_parent_track_id",
        _arrange_nested_anthropic_subagent,
        (
            ExpectedAnchor(
                "child",
                "toolu_child",
                ROOT_RUN_ID,
                "ex-root-spawn",
                "toolu_child",
                0,
            ),
            ExpectedAnchor(
                "grandchild",
                "toolu_grandchild",
                "toolu_child",
                "ex-child-spawn",
                "toolu_grandchild",
                0,
            ),
        ),
    ),
    AnchorCase(
        "test_anthropic_agent_tool_result_closure_preserves_spawn_anchor",
        _arrange_anthropic_closure_preserves_spawn_anchor,
        (
            ExpectedAnchor(
                "closed",
                "toolu_close_anchor",
                ROOT_RUN_ID,
                "ex-anthropic-spawn",
                "toolu_close_anchor",
                0,
                "research",
            ),
        ),
        _assert_anthropic_closed_spawn_anchor,
    ),
    AnchorCase(
        "test_codex_nested_subagent_anchors_to_parent_track_exchange",
        _arrange_codex_nested_subagent,
        (
            ExpectedAnchor(
                "child",
                CODEX_AGENT_ID,
                ROOT_RUN_ID,
                "ex-root-spawn",
                CODEX_SPAWN_ID,
                0,
                "worker",
            ),
            ExpectedAnchor(
                "grandchild",
                "019dc432-c4bc-75d2-a8e5-fffffffffff1",
                CODEX_AGENT_ID,
                "ex-child-spawn",
                "call_grandchild_spawn",
                0,
                "nested",
            ),
        ),
    ),
    AnchorCase(
        "test_codex_failed_spawn_result_does_not_open_track",
        _arrange_codex_failed_spawn_result,
        (
            ExpectedAnchor("assignment", ROOT_RUN_ID, None, None, None, None),
            ExpectedAnchor("parent", ROOT_RUN_ID, None, None, None, None),
        ),
        _assert_codex_failed_spawn,
    ),
)


@pytest.mark.parametrize(
    "case",
    ANCHOR_CASES,
    ids=[case.name for case in ANCHOR_CASES],
)
def test_track_manager_spawn_anchor_cases(case: AnchorCase) -> None:
    manager = TrackManager()
    assignments = case.arrange(manager)

    for expected in case.expected:
        assignment = assignments[expected.assignment_key]
        assert assignment.track_id == expected.track_id
        assert assignment.parent_track_id == expected.parent_track_id
        if expected.display_name is not None:
            assert assignment.track_display_name == expected.display_name
        if expected.exchange_id is None:
            assert assignment.spawn_anchor is None
            continue
        assert assignment.spawn_anchor is not None
        assert assignment.spawn_anchor.track_spawn_exchange_id == expected.exchange_id
        assert assignment.spawn_anchor.track_spawn_tool_use_id == expected.tool_use_id
        assert assignment.spawn_anchor.track_spawn_order == expected.order

    if case.assert_case is not None:
        case.assert_case(manager, assignments)
