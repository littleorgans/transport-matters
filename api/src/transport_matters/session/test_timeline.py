from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from transport_matters.session.models import ChildSessionRow, EventRow
from transport_matters.session.test_foundation import event, root_session
from transport_matters.session.timeline import project_timeline

if TYPE_CHECKING:
    from transport_matters.session.timeline_models import TimelineResponse


def _json(response: TimelineResponse) -> dict[str, Any]:
    return response.model_dump(mode="json", by_alias=True)


def _meta(seq: int, raw: dict[str, object]) -> EventRow:
    return event(seq).model_copy(update={"kind": "meta", "raw": raw, "ir": None, "role": None})


def _child_session() -> ChildSessionRow:
    child = root_session("child", native_session_id="child-native").model_copy(
        update={
            "parent_session_id": "s1",
            "forked_at_seq": 0,
            "title": "Code reviewer",
        }
    )
    return ChildSessionRow.model_validate(
        child.model_dump(mode="python") | {"first_seq": 0, "last_seq": 2}
    )


def test_projector_maps_turn_rows_to_message_items() -> None:
    response = project_timeline(session=root_session(), events=[event(0)], next_from_seq=1)

    payload = _json(response)

    assert payload["nextFromSeq"] == 1
    assert payload["session"]["sessionId"] == "s1"
    assert payload["items"] == [
        {
            "kind": "message",
            "id": "message:s1:0",
            "seq": 0,
            "role": "assistant",
            "ts": "2026-06-06T00:00:00+00:00",
            "model": None,
            "parts": [{"type": "text", "text": "alpha beta"}],
            "resourceRefs": [],
            "subagentRefs": [],
            "badges": [],
            "source": {
                "sessionId": "s1",
                "seq": 0,
                "eventKind": "turn",
                "sourcePath": "/tmp/s1.jsonl",
                "sourceLine": 0,
                "rawAvailable": True,
                "irAvailable": True,
            },
        }
    ]


@pytest.mark.parametrize(
    ("raw", "expected_kind", "expected_label"),
    [
        (
            {"type": "attachment", "attachment": {"type": "output_style", "name": "concise"}},
            "state",
            "Output style",
        ),
        (
            {"type": "attachment", "attachment": {"type": "skill_listing", "name": "skills"}},
            "context",
            "Skill listing",
        ),
        (
            {"type": "attachment", "attachment": {"type": "deferred_tools_delta"}},
            "context",
            "Deferred tools delta",
        ),
        (
            {"type": "attachment", "attachment": {"type": "mcp_instructions_delta"}},
            "context",
            "MCP instructions delta",
        ),
        (
            {"type": "attachment", "attachment": {"type": "hook_additional_context"}},
            "context",
            "Hook context",
        ),
        (
            {"type": "attachment", "attachment": {"type": "hook_success"}},
            "diagnostic",
            "Hook success",
        ),
        ({"type": "system", "subtype": "stop_hook_summary"}, "diagnostic", "Stop hook summary"),
        ({"type": "mode", "mode": "default"}, "state", "Mode"),
        ({"type": "permission-mode", "mode": "plan"}, "state", "Permission mode"),
        ({"type": "file-history-snapshot"}, "context", "File history snapshot"),
        ({"type": "event_msg", "message": "working"}, "context", "Progress event"),
    ],
)
def test_projector_maps_meta_records(
    raw: dict[str, object], expected_kind: str, expected_label: str
) -> None:
    response = project_timeline(session=root_session(), events=[_meta(1, raw)])

    item = _json(response)["items"][0]

    assert item["kind"] == expected_kind
    assert item["label"] == expected_label
    assert item["source"]["rawAvailable"] is True
    assert item["source"]["irAvailable"] is False


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "last-prompt"},
        {"type": "ai-title", "title": "Run tests"},
        {"type": "session_meta"},
        {"type": "turn_context"},
    ],
)
def test_projector_keeps_metadata_only_records_out_of_items(raw: dict[str, object]) -> None:
    response = project_timeline(session=root_session(), events=[_meta(1, raw)])

    assert _json(response)["items"] == []


def test_projector_maps_turn_duration_to_prior_message_badge() -> None:
    response = project_timeline(
        session=root_session(),
        events=[event(0), _meta(1, {"type": "system", "subtype": "turn_duration", "ms": 42})],
    )

    items = _json(response)["items"]

    assert len(items) == 1
    assert items[0]["badges"] == [{"label": "Turn duration", "value": "42 ms", "tone": "neutral"}]


def test_projector_emits_child_and_virtual_sidechain_subagents() -> None:
    sidechain = event(1).model_copy(
        update={
            "native_turn_id": "sidechain-turn",
            "parent_native_id": "turn0",
            "parent_seq": 0,
            "is_sidechain": True,
        }
    )

    response = project_timeline(
        session=root_session(),
        events=[event(0), sidechain],
        child_sessions=[_child_session()],
    )
    payload = _json(response)

    subagents = payload["subagents"]
    assert subagents["subagent-session:child"]["mode"] == "child-session"
    virtual_ids = [key for key in subagents if key.startswith("subagent-sidechain:s1:")]
    assert len(virtual_ids) == 1
    assert subagents[virtual_ids[0]]["mode"] == "virtual-sidechain"

    items = payload["items"]
    assert [item["kind"] for item in items] == ["message", "subagent", "subagent"]
    assert len(items[0]["subagentRefs"]) == 2
    assert {hint["target"]["kind"] for hint in payload["layoutHints"]} == {"subagent-timeline"}
