"""Tier-2 capture-and-retrieval substrate (the rebuildable SQLite projection of tier-1).

Core store + single-writer actor (slice 1), wire ingest + sink (slice 2), read/query API
(slice 3), the transcript adapter port + claude adapter + transcript ingest (slice 4a), the
file tailer + live ``transcript_turn`` event (slice 4b), and the durable run enumerator +
tier-2 delete + block GC (slice 8a, ``maintenance.py``).
"""

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
from transport_matters.index.blocks import (
    IndexablePart,
    block_hash,
    block_kind,
    block_text,
    identity_canonical,
    upsert_block,
)
from transport_matters.index.db import connect, index_db_path, transaction
from transport_matters.index.ingest import build_transcript_job
from transport_matters.index.maintenance import (
    RunDir,
    delete_exchange,
    delete_run,
    gc_blocks,
    iter_run_dirs,
)
from transport_matters.index.models import (
    BlockEdge,
    SessionRow,
    TranscriptTurnRow,
    WireExchangeRow,
)
from transport_matters.index.schema import apply_schema, rebuild_fts
from transport_matters.index.sessions import SESSION_NS, synth_session_id, upsert_session
from transport_matters.index.writer import IndexJob, IndexWriter

__all__ = [
    "SESSION_NS",
    "BlockEdge",
    "FileTailSource",
    "IndexJob",
    "IndexWriter",
    "IndexablePart",
    "NormalizedTurn",
    "PullSource",
    "RunContext",
    "RunDir",
    "SessionBinding",
    "SessionRow",
    "TranscriptAdapter",
    "TranscriptSource",
    "TranscriptTurnRow",
    "TurnContext",
    "WireExchangeRow",
    "apply_schema",
    "block_hash",
    "block_kind",
    "block_text",
    "build_transcript_job",
    "connect",
    "delete_exchange",
    "delete_run",
    "gc_blocks",
    "get_adapter",
    "identity_canonical",
    "index_db_path",
    "iter_run_dirs",
    "rebuild_fts",
    "synth_session_id",
    "transaction",
    "upsert_block",
    "upsert_session",
]
