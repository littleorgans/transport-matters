"""Continuation launch support for the managed run API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from transport_matters.session.async_dao import AsyncSessionDao
from transport_matters.session.models import EventRow, SessionPurpose

if TYPE_CHECKING:
    from psycopg import AsyncConnection
    from psycopg.rows import DictRow
    from psycopg_pool import AsyncConnectionPool


class ContinuationSessionNotFound(LookupError):
    """Raised when an owner scoped parent session lookup misses."""


@dataclass(frozen=True, slots=True)
class ContinuationLaunchFields:
    """Validated launch fields for a continuation run."""

    fields: dict[str, object]


async def build_continuation_launch_fields(
    pool: AsyncConnectionPool[AsyncConnection[DictRow]],
    *,
    parent_session_id: str,
    owner: str,
) -> ContinuationLaunchFields:
    """Validate the parent session and build field agnostic launch metadata."""
    async with pool.connection() as conn:
        dao = AsyncSessionDao(conn)
        parent = await dao.get_session_for_owner(parent_session_id, owner=owner)
        if parent is None:
            raise ContinuationSessionNotFound(parent_session_id)
        fork_event = await dao.get_latest_turn_with_raw_for_owner(parent_session_id, owner=owner)
        first_user = await dao.get_first_turn_with_raw_for_owner(
            parent_session_id, owner=owner, role="user"
        )
        last_assistant = await dao.get_latest_turn_with_raw_for_owner(
            parent_session_id, owner=owner, role="assistant"
        )

    forked_at_seq = fork_event.seq if fork_event is not None else 0
    return ContinuationLaunchFields(
        fields={
            "continue_from_session_id": parent_session_id,
            "parent_session_id": parent_session_id,
            "forked_at_seq": forked_at_seq,
            "session_purpose": SessionPurpose.CONTINUATION.value,
            "resume_context": {
                "firstUserPrompt": _event_text(first_user),
                "lastAgentMessage": _event_text(last_assistant),
                "transcriptRef": parent_session_id,
            },
        }
    )


def _event_text(row: EventRow | None) -> str | None:
    if row is None:
        return None
    if row.search_text:
        return row.search_text
    parts = [] if row.ir is None else row.ir.get("parts")
    if not isinstance(parts, list):
        return None
    text = "\n".join(
        part["text"]
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str) and part["text"]
    )
    return text or None
