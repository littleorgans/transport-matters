from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from transport_matters.session.models import ChildSessionRow, EventRow
from transport_matters.session.test_foundation import event, root_session, tool_result_event
from transport_matters.session.timeline import project_timeline, required_timeline_anchor_before_seq
from transport_matters.session.timeline_models import (
    SessionUpdatedStreamEvent,
    SubagentUpdatedStreamEvent,
    TimelineItemStreamEvent,
)
from transport_matters.session.timeline_stream import project_timeline_stream_envelopes

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


def test_stream_projection_reuses_backlog_item_and_resource_shapes() -> None:
    session = root_session()
    rows = [tool_result_event(0, text="stdout"), tool_result_event(1, text="stderr")]
    backlog = project_timeline(session=session, events=rows)

    envelopes = project_timeline_stream_envelopes(
        session=session,
        events=rows,
        emitted_at="2026-06-06T00:00:00+00:00",
    )

    resource_id = "tool-output:s1:0:0"
    assert set(backlog.resources) == {resource_id, "tool-output:s1:1:0"}
    assert len(envelopes) == 4
    assert envelopes[0].id == "timeline:s1:0"
    assert envelopes[0].revision == 0
    assert envelopes[0].event == TimelineItemStreamEvent(
        item=backlog.items[0],
        resources={resource_id: backlog.resources[resource_id]},
    )


def test_stream_projection_emits_session_update_envelope_with_revision() -> None:
    session = root_session()
    backlog = project_timeline(session=session, events=[])

    envelopes = project_timeline_stream_envelopes(
        session=session,
        events=[],
        include_session_update=True,
        emitted_at="2026-06-06T00:00:00+00:00",
    )

    assert len(envelopes) == 1
    assert envelopes[0].id == "session:s1"
    assert envelopes[0].revision == int(session.started_at.timestamp() * 1000)
    assert envelopes[0].event == SessionUpdatedStreamEvent(session=backlog.session)


def test_stream_projection_emits_subagent_update_envelope_with_revision() -> None:
    session = root_session()
    child = _child_session()
    backlog = project_timeline(session=session, events=[event(0)], child_sessions=[child])

    envelopes = project_timeline_stream_envelopes(
        session=session,
        events=[event(0)],
        child_sessions=[child],
        emitted_at="2026-06-06T00:00:00+00:00",
    )
    subagent_envelope = next(
        item for item in envelopes if item.id == "subagent:s1:subagent-session:child"
    )

    assert subagent_envelope.revision == 2
    assert subagent_envelope.event == SubagentUpdatedStreamEvent(
        subagent=backlog.subagents["subagent-session:child"]
    )


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


def test_projector_emits_only_child_session_subagents() -> None:
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
    assert list(subagents) == ["subagent-session:child"]
    assert "mode" not in subagents["subagent-session:child"]

    items = payload["items"]
    assert [item["kind"] for item in items] == ["message", "subagent", "message"]
    assert len(items[0]["subagentRefs"]) == 1
    child_item = next(item for item in items if item["kind"] == "subagent")
    assert child_item["source"]["eventKind"] == "turn"
    assert {hint["target"]["kind"] for hint in payload["layoutHints"]} == {"subagent-timeline"}


def test_projector_links_child_forked_at_meta_to_prior_message() -> None:
    child = _child_session().model_copy(update={"forked_at_seq": 1})

    response = project_timeline(
        session=root_session(),
        events=[event(0), _meta(1, {"type": "mode", "mode": "default"})],
        child_sessions=[child],
    )
    items = _json(response)["items"]

    assert items[0]["kind"] == "message"
    assert items[0]["subagentRefs"] == [
        {
            "subagentId": "subagent-session:child",
            "sessionId": "child",
            "parentSessionId": "s1",
            "parentSeq": 1,
            "title": "Code reviewer",
        }
    ]


def test_projector_emits_child_when_fork_seq_is_gap_in_page() -> None:
    child = _child_session().model_copy(update={"forked_at_seq": 1})

    response = project_timeline(
        session=root_session(),
        events=[event(0), event(2)],
        child_sessions=[child],
    )
    payload = _json(response)

    assert "subagent-session:child" in payload["subagents"]
    assert [item["kind"] for item in payload["items"]] == ["message", "subagent", "message"]
    assert payload["items"][0]["subagentRefs"][0]["parentSeq"] == 1


def test_projector_emits_child_when_fork_seq_is_page_lower_bound_gap() -> None:
    child = _child_session().model_copy(update={"forked_at_seq": 1})

    response = project_timeline(
        session=root_session(),
        events=[event(2)],
        child_sessions=[child],
        page_from_seq=1,
    )
    payload = _json(response)

    assert "subagent-session:child" in payload["subagents"]
    assert [item["kind"] for item in payload["items"]] == ["subagent", "message"]


def test_projector_does_not_emit_virtual_sidechain_for_sidechain_meta() -> None:
    sidechain_meta = _meta(1, {"type": "event_msg", "message": "working"}).model_copy(
        update={
            "parent_native_id": "turn0",
            "parent_seq": 0,
            "is_sidechain": True,
        }
    )

    response = project_timeline(
        session=root_session(),
        events=[event(0), sidechain_meta],
    )
    payload = _json(response)

    assert [item["kind"] for item in payload["items"]] == ["message", "context"]
    assert payload["items"][0]["subagentRefs"] == []
    assert payload["subagents"] == {}
    assert payload["layoutHints"] == []


def test_required_timeline_anchor_treats_sidechain_turns_as_regular_turns() -> None:
    sidechain = event(0).model_copy(update={"is_sidechain": True})

    assert (
        required_timeline_anchor_before_seq(
            [sidechain, _meta(1, {"type": "system", "subtype": "turn_duration", "ms": 42})]
        )
        is None
    )


def test_projector_does_not_emit_debug_native_resources_in_slice_one() -> None:
    response = project_timeline(
        session=root_session(),
        events=[_meta(1, {"type": "event_msg", "message": "working"})],
        include_debug=True,
    )
    payload = _json(response)

    assert payload["resources"] == {}
    assert payload["items"][0]["resourceRefs"] == []
