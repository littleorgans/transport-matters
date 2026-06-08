from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from transport_matters.session.models import ChildSessionRow, EventArtifactRow, EventRow
from transport_matters.session.test_foundation import event, root_session
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


def _inline_artifact_event() -> EventRow:
    return event(0).model_copy(
        update={
            "ir": {
                "parts": [
                    {
                        "type": "image",
                        "artifact_hash": "sha256-inline-1",
                        "media_type": "image/png",
                    },
                    {"type": "text", "text": "alpha beta"},
                ],
                "exchange_id": "exchange-1",
            },
            "artifacts": (
                EventArtifactRow(
                    session_id="s1",
                    seq=0,
                    artifact_hash="sha256-inline-1",
                    ref={"block_index": 0},
                    media_type="image/png",
                    size_bytes=11,
                ),
            ),
        }
    )


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
            "resourceRefs": [
                {
                    "resourceId": "native:s1:0",
                    "relation": "native-record",
                    "confidence": "verified",
                    "blockIndex": None,
                }
            ],
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
    rows = [_inline_artifact_event()]
    backlog = project_timeline(session=session, events=rows)

    envelopes = project_timeline_stream_envelopes(
        session=session,
        events=rows,
        emitted_at="2026-06-06T00:00:00+00:00",
    )

    assert set(backlog.resources) == {
        "inline:sha256-inline-1",
        "native:s1:0",
        "wire:exchange-1",
    }
    assert len(envelopes) == 4
    assert envelopes[0].id == "timeline:s1:0"
    assert envelopes[0].revision == 0
    assert envelopes[0].event == TimelineItemStreamEvent(
        item=backlog.items[0],
        resources=backlog.resources,
    )


def test_projector_emits_conservative_resource_refs_for_inline_native_and_wire() -> None:
    response = project_timeline(session=root_session(), events=[_inline_artifact_event()])
    payload = _json(response)

    assert payload["items"][0]["resourceRefs"] == [
        {
            "resourceId": "native:s1:0",
            "relation": "native-record",
            "confidence": "verified",
            "blockIndex": None,
        },
        {
            "resourceId": "inline:sha256-inline-1",
            "relation": "attached",
            "confidence": "verified",
            "blockIndex": 0,
        },
        {
            "resourceId": "wire:exchange-1",
            "relation": "wire-evidence",
            "confidence": "verified",
            "blockIndex": None,
        },
    ]
    assert payload["resources"]["inline:sha256-inline-1"] == {
        "kind": "inline",
        "id": "inline:sha256-inline-1",
        "title": "Inline artifact",
        "mediaType": "image/png",
        "artifactHash": "sha256-inline-1",
        "sizeBytes": 11,
    }
    assert payload["resources"]["native:s1:0"]["source"] == payload["items"][0]["source"]
    assert payload["resources"]["wire:exchange-1"] == {
        "kind": "wire",
        "id": "wire:exchange-1",
        "title": "Wire exchange",
        "exchangeId": "exchange-1",
        "structuredOnly": True,
    }


def test_projector_does_not_emit_verified_file_refs_for_mentioned_path() -> None:
    mentioned = event(0, search_text="Mentioned NOTES/demo.md").model_copy(
        update={
            "ir": {
                "parts": [{"type": "text", "text": "Mentioned NOTES/demo.md"}],
            },
        }
    )

    payload = _json(project_timeline(session=root_session(), events=[mentioned]))

    assert payload["items"][0]["resourceRefs"] == [
        {
            "resourceId": "native:s1:0",
            "relation": "native-record",
            "confidence": "verified",
            "blockIndex": None,
        }
    ]
    assert all(not resource_id.startswith("file-") for resource_id in payload["resources"])


def test_projector_does_not_emit_wire_ref_when_exchange_id_is_absent() -> None:
    payload = _json(project_timeline(session=root_session(), events=[event(0)]))

    assert payload["items"][0]["resourceRefs"] == [
        {
            "resourceId": "native:s1:0",
            "relation": "native-record",
            "confidence": "verified",
            "blockIndex": None,
        }
    ]
    assert all(not resource_id.startswith("wire:") for resource_id in payload["resources"])


def test_projector_does_not_trust_provider_raw_exchange_keys() -> None:
    provider_raw = event(0).model_copy(
        update={
            "raw": {
                "turn": {"exchange_id": "provider-turn"},
                "correlation": {"exchangeId": "provider-correlation"},
            },
        }
    )

    payload = _json(project_timeline(session=root_session(), events=[provider_raw]))

    assert payload["items"][0]["resourceRefs"] == [
        {
            "resourceId": "native:s1:0",
            "relation": "native-record",
            "confidence": "verified",
            "blockIndex": None,
        }
    ]
    assert all(not resource_id.startswith("wire:") for resource_id in payload["resources"])


def test_projector_dedupes_inline_artifact_by_hash_when_block_index_disagrees() -> None:
    mismatched_inline = event(0).model_copy(
        update={
            "ir": {
                "parts": [
                    {
                        "type": "image",
                        "artifact_hash": "sha256-inline-mismatch",
                        "media_type": "image/png",
                    },
                    {"type": "text", "text": "caption"},
                ],
            },
            "artifacts": (
                EventArtifactRow(
                    session_id="s1",
                    seq=0,
                    artifact_hash="sha256-inline-mismatch",
                    ref={"block_index": 1},
                    media_type="image/png",
                    size_bytes=17,
                ),
            ),
        }
    )

    payload = _json(project_timeline(session=root_session(), events=[mismatched_inline]))

    assert payload["items"][0]["resourceRefs"] == [
        {
            "resourceId": "native:s1:0",
            "relation": "native-record",
            "confidence": "verified",
            "blockIndex": None,
        },
        {
            "resourceId": "inline:sha256-inline-mismatch",
            "relation": "attached",
            "confidence": "verified",
            "blockIndex": 0,
        },
    ]
    assert [
        resource_id for resource_id in payload["resources"] if resource_id.startswith("inline:")
    ] == ["inline:sha256-inline-mismatch"]


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


def test_projector_emits_native_refs_for_context_items() -> None:
    response = project_timeline(
        session=root_session(),
        events=[_meta(1, {"type": "event_msg", "message": "working"})],
        include_debug=True,
    )
    payload = _json(response)

    assert payload["items"][0]["resourceRefs"] == [
        {
            "resourceId": "native:s1:1",
            "relation": "native-record",
            "confidence": "verified",
            "blockIndex": None,
        }
    ]
    assert payload["resources"]["native:s1:1"]["kind"] == "native-record"
