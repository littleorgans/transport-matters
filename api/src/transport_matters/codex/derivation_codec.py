"""Persistence codecs for Codex derived artifacts."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from transport_matters.codex.events import CodexSemanticEvent, CodexTurnSummary


def serialize_codex_events_jsonl(events: Sequence[CodexSemanticEvent]) -> bytes:
    if not events:
        return b""
    body = "".join(f"{event.model_dump_json()}\n" for event in events)
    return body.encode()


def serialize_codex_turn_json(turn: CodexTurnSummary) -> bytes:
    return turn.model_dump_json(indent=2).encode()


__all__ = [
    "serialize_codex_events_jsonl",
    "serialize_codex_turn_json",
]
