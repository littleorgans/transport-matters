"""Shared test builders for the disk storage backend.

Imported by sibling ``test_disk_*.py`` modules as ``disk_tests``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from transport_matters.codex.derivation import CODEX_DERIVATION_VERSION
from transport_matters.codex.events import (
    CodexDerivationCursor,
    CodexOpenAssistantItem,
    CodexSemanticEvent,
    CodexTransportRef,
    CodexTurnSummary,
)
from transport_matters.ir import (
    InternalRequest,
    Message,
    RequestMetadata,
    SamplingParams,
    TextBlock,
)
from transport_matters.overrides import OverrideAudit, OverrideAuditEntry
from transport_matters.storage.base import (
    IndexEntry,
    ReqStats,
)


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


def _make_index_entry(entry_id: str = "ex-001") -> IndexEntry:
    return IndexEntry(
        id=entry_id,
        ts=datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC),
        provider="anthropic",
        model="anthropic/claude-sonnet-4-20250514",
        path="/v1/messages",
        req=ReqStats(
            system_parts=0,
            system_chars=0,
            tools_count=0,
            tools_chars=0,
            messages_count=1,
            messages_chars=2,
            total_chars=2,
        ),
    )


def _make_audit() -> OverrideAudit:
    return OverrideAudit(
        entries=[
            OverrideAuditEntry(
                kind="system_part_text",
                target="system:0",
                applied=True,
                chars_delta=-3,
                curated_value="patched",
            )
        ],
        chars_before=10,
        chars_after=7,
    )


def _make_codex_event(event_id: str = "evt_000001") -> CodexSemanticEvent:
    return CodexSemanticEvent(
        event_id=event_id,
        exchange_id="codex-exchange-001",
        session_id="ws_123",
        turn_id="turn_001",
        seq=1,
        ts=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
        source="client",
        kind="turn_started",
        transport_ref=CodexTransportRef(message_index=0),
        derivation_version=CODEX_DERIVATION_VERSION,
    )


def _make_open_turn() -> CodexTurnSummary:
    return CodexTurnSummary(
        turn_id="turn_001",
        exchange_id="codex-exchange-001",
        session_id="ws_123",
        turn_index=0,
        request_message_index=0,
        message_range_start=0,
        message_range_end=0,
        model="codex/gpt-5-codex",
        status="open",
        text_chars=12,
        tool_calls=0,
        started_at=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
        derivation_version=CODEX_DERIVATION_VERSION,
        cursor=CodexDerivationCursor(
            next_message_index=1,
            next_seq=2,
            open_assistant_items={
                "msg_01": CodexOpenAssistantItem(text="partial assistant text")
            },
            open_tool_calls={},
            terminal_seen=False,
        ),
    )


def _make_completed_turn() -> CodexTurnSummary:
    return CodexTurnSummary(
        turn_id="turn_001",
        exchange_id="codex-exchange-001",
        session_id="ws_123",
        turn_index=0,
        request_message_index=0,
        terminal_message_index=2,
        terminal_cause="response_completed",
        message_range_start=0,
        message_range_end=2,
        model="codex/gpt-5-codex",
        status="completed",
        stop_reason="completed",
        text_chars=42,
        tool_calls=1,
        started_at=datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC),
        ended_at=datetime(2026, 4, 19, 12, 0, 2, tzinfo=UTC),
        derivation_version=CODEX_DERIVATION_VERSION,
        cursor=CodexDerivationCursor(
            next_message_index=3,
            next_seq=4,
            open_assistant_items={},
            open_tool_calls={},
            terminal_seen=True,
        ),
    )
