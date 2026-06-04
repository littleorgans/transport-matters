"""Frozen Pydantic row models mirroring the tier-2 tables (§3.4-3.5).

Read-side typed representations of each table. Nullability matches the DDL exactly so a
``SELECT *`` round-trips into one of these without coercion. Identity/text columns on
``BlockRow`` are immutable; only ``n_tokens`` is ever back-filled (§3.3).
"""

from pydantic import BaseModel, ConfigDict


class BlockRow(BaseModel):
    """One row of ``block``: a content-addressed unit shared across both streams."""

    model_config = ConfigDict(frozen=True)

    id: int
    hash: str
    kind: str
    text: str
    identity_canonical: str
    n_tokens: int | None
    created_at: str


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
