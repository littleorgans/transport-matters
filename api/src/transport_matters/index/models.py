"""Frozen Pydantic row models mirroring the tier-2 tables (§3.4-3.5).

Read-side typed representations of each table. Nullability matches the DDL exactly so a
``SELECT *`` round-trips into one of these without coercion.
"""

from pydantic import BaseModel, ConfigDict


class SessionRow(BaseModel):
    """One row of ``session``: the correlation anchor between wire and transcript."""

    model_config = ConfigDict(frozen=True)

    session_id: str
    provider: str
    cli: str | None
    run_id: str
    cwd: str
    workspace_slug: str
    workspace_hash: str
    native_session_id: str | None
    minted: int
    source_descriptor: str | None
    started_at: str


class WireExchangeRow(BaseModel):
    """One row of ``wire_exchange``: a captured request→response round trip."""

    model_config = ConfigDict(frozen=True)

    exchange_id: str
    session_id: str | None
    run_id: str
    provider: str
    model: str
    ts: str
    seq: int | None
    req_system_chars: int | None
    req_tools_chars: int | None
    req_messages_chars: int | None
    req_tokens: int | None
    res_tokens: int | None
    stop_reason: str | None
    mutated_manually: int
    raw_dir: str


class TranscriptTurnRow(BaseModel):
    """One row of ``transcript_turn``: a single harness turn under a bound session."""

    model_config = ConfigDict(frozen=True)

    turn_id: str
    session_id: str
    run_id: str
    provider: str
    cli: str
    parent_id: str | None
    role: str
    seq: int
    ts: str | None
    is_sidechain: int
    model: str | None
    source_path: str
    source_line: int | None


class BlockEdge(BaseModel):
    """One ordered block reference (``exchange_block`` or ``turn_block``).

    Role, stream, section, and position live on the edge, never on the block — that is what
    lets identical content authored under different roles/streams dedup to one block (§3.5).
    ``section`` is set for ``exchange_block`` (which IR region) and ``None`` for ``turn_block``.
    """

    model_config = ConfigDict(frozen=True)

    entity_id: str
    pos: int
    block_id: int
    role: str
    section: str | None = None


# ── Read / query result models (§8) ─────────────────────────────────


class SearchFilters(BaseModel):
    """Optional, AND-combined filters for ``search_blocks`` (§8.2)."""

    model_config = ConfigDict(frozen=True)

    kind: str | None = None
    stream: str | None = None
    provider: str | None = None
    cli: str | None = None
    role: str | None = None
    section: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    since: str | None = None
    until: str | None = None
    is_sidechain: int | None = None


class SessionFilters(BaseModel):
    """Optional, AND-combined filters for ``list_sessions`` (§8.6)."""

    model_config = ConfigDict(frozen=True)

    workspace_hash: str | None = None
    run_id: str | None = None
    provider: str | None = None
    cli: str | None = None


class BlockHit(BaseModel):
    """One search hit: phase-1 metadata + snippet + bm25 rank, no body (§8.2)."""

    model_config = ConfigDict(frozen=True)

    id: int
    hash: str
    kind: str
    n_tokens: int | None
    snippet: str
    rank: float
    # Occurrence-centric (one row per edge); None in block-centric mode.
    stream: str | None = None
    entity_id: str | None = None
    role: str | None = None
    section: str | None = None
    session_id: str | None = None
    ts: str | None = None
    run_id: str | None = None
    provider: str | None = None
    # Block-centric aggregates; None in occurrence mode.
    occurrences: int | None = None
    sessions: str | None = None


class BlockBody(BaseModel):
    """One block body: phase-2 full content for chosen ids (§8.2)."""

    model_config = ConfigDict(frozen=True)

    id: int
    hash: str
    kind: str
    text: str
    identity_canonical: str
    n_tokens: int | None


class TimelineBlock(BaseModel):
    """One ordered block reference within a timeline entry (§8.3)."""

    model_config = ConfigDict(frozen=True)

    pos: int
    block_id: int
    role: str
    section: str | None = None  # set for wire exchange_block; None for turn_block
    text: str | None = None  # inlined only when with_bodies
    identity_canonical: str | None = None  # inlined only when with_bodies


class TimelineEntry(BaseModel):
    """One exchange or turn in a session timeline, with its ordered blocks (§8.3)."""

    model_config = ConfigDict(frozen=True)

    stream: str
    entity_id: str
    seq: int | None
    ts: str | None
    parent_id: str | None = None  # transcript DAG link (turn tree)
    is_sidechain: int = 0
    blocks: list[TimelineBlock]


class Correspondence(BaseModel):
    """One wire-exchange ↔ transcript-turn correspondence, ranked by shared blocks (§8.4)."""

    model_config = ConfigDict(frozen=True)

    exchange_id: str
    turn_id: str
    shared_blocks: int


class SessionDiff(BaseModel):
    """The §1.1 block-set DIFF within a session: three block-id buckets (§8.4)."""

    model_config = ConfigDict(frozen=True)

    wire_only: list[int]
    transcript_only: list[int]
    shared: list[int]


class RawRef(BaseModel):
    """A tier-1 raw-bytes pointer for one wire exchange (§8.5; no bytes in tier-2)."""

    model_config = ConfigDict(frozen=True)

    exchange_id: str
    raw_dir: str
    request_raw: str
    response_raw: str
