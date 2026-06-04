"""Tier-2 capture-and-retrieval substrate (the rebuildable SQLite projection of tier-1).

Slice 1 ships the core store and single-writer actor: schema + PRAGMAs, the content-addressed
block layer, session correlation, frozen row models, and the ``IndexWriter`` thread. Wire/
transcript ingest, the query API, live-tail, and GC land in later slices.
"""

from transport_matters.index.blocks import (
    IndexablePart,
    block_hash,
    block_kind,
    block_text,
    identity_canonical,
    upsert_block,
)
from transport_matters.index.db import connect, index_db_path, transaction
from transport_matters.index.models import (
    BlockEdge,
    BlockRow,
    SessionRow,
    TranscriptTurnRow,
    WireExchangeRow,
)
from transport_matters.index.schema import apply_schema, rebuild_fts
from transport_matters.index.sessions import (
    SESSION_NS,
    SessionBinding,
    resolve_session_id,
    synth_session_id,
    upsert_session,
)
from transport_matters.index.writer import IndexJob, IndexWriter

__all__ = [
    "SESSION_NS",
    "BlockEdge",
    "BlockRow",
    "IndexJob",
    "IndexWriter",
    "IndexablePart",
    "SessionBinding",
    "SessionRow",
    "TranscriptTurnRow",
    "WireExchangeRow",
    "apply_schema",
    "block_hash",
    "block_kind",
    "block_text",
    "connect",
    "identity_canonical",
    "index_db_path",
    "rebuild_fts",
    "resolve_session_id",
    "synth_session_id",
    "transaction",
    "upsert_block",
    "upsert_session",
]
