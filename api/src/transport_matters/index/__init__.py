"""Transcript adapter utilities that still back the session store."""

from transport_matters.index.adapters import get_adapter
from transport_matters.index.adapters.base import (
    FileTailSource,
    NormalizedTurn,
    PullSource,
    RunContext,
    SessionBinding,
    TranscriptAdapter,
    TranscriptSource,
    TurnContext,
)
from transport_matters.index.sessions import SESSION_NS, synth_session_id
from transport_matters.index.tailer import (
    TailCursor,
    TranscriptTailer,
    ingest_records,
    iter_complete_records,
    register_session_cursor,
)

__all__ = [
    "SESSION_NS",
    "FileTailSource",
    "NormalizedTurn",
    "PullSource",
    "RunContext",
    "SessionBinding",
    "TailCursor",
    "TranscriptAdapter",
    "TranscriptSource",
    "TranscriptTailer",
    "TurnContext",
    "get_adapter",
    "ingest_records",
    "iter_complete_records",
    "register_session_cursor",
    "synth_session_id",
]
