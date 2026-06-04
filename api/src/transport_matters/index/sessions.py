"""Session correlation: the frozen synthesis namespace, deterministic synth, and upsert.

The ``session_id`` is the universal correlation key between the wire and transcript
streams. Where we mint it (claude/gemini) it is authoritative; where we read it back
(codex) it is a deterministic ``uuid5`` over the frozen ``SESSION_NS`` so re-ingest of the
same native id converges on the same PK (§3.4). Shared by the §5 read-back adapters and the
§7.2 wire correlation so both streams land on one ``session_id`` (the pivot, §2).
"""

import uuid
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    import sqlite3

# Frozen namespace for read-back session_id synthesis. It is seeded into
# schema_meta.session_ns and gated on boot, so bumping it is a schema-version change that
# forces a drop + rebuild (§3.2/§3.4). Never change it without bumping schema_version.
SESSION_NS = uuid.UUID("a3f1c2d4-5e6b-4a7c-8d9e-0f1a2b3c4d5e")


class SessionBinding(BaseModel):
    """Pre-write binding facts that resolve to exactly one ``session`` row.

    Slice-1 local staging of the shared model ``index/adapters/base.py`` will own in slice 4
    (§4.2); both the wire correlation and the transcript adapters build one of these. The
    ``session_id`` is DERIVED here (minted passthrough or read-back synth), so it is not a
    binding input.
    """

    model_config = ConfigDict(frozen=True)

    provider: str
    run_id: str
    cwd: str
    workspace_slug: str
    workspace_hash: str
    started_at: str
    cli: str | None = None
    native_session_id: str | None = None
    minted_session_id: str | None = None  # the minted CLI session_id (claude/gemini), if any
    source_descriptor: str | None = None


def synth_session_id(run_id: str, provider: str, native_session_id: str) -> str:
    """Deterministically synthesize a read-back ``session_id`` (§3.4).

    ``uuid5`` over the frozen ``SESSION_NS``, so re-ingesting the same native id yields the
    same PK → upsert (idempotent). Pure, so the wire correlation and the transcript adapter
    independently compute the same value and the pivot joins.
    """
    return str(uuid.uuid5(SESSION_NS, f"{run_id}|{provider}|{native_session_id}"))


def resolve_session_id(binding: SessionBinding) -> str:
    """Resolve a binding's ``session_id``: minted passthrough, else read-back synth."""
    if binding.minted_session_id is not None:
        return binding.minted_session_id
    if binding.native_session_id is None:
        raise ValueError("read-back SessionBinding requires native_session_id or minted_session_id")
    return synth_session_id(binding.run_id, binding.provider, binding.native_session_id)


def upsert_session(conn: sqlite3.Connection, binding: SessionBinding) -> str:
    """Upsert one ``session`` row keyed by the resolved ``session_id`` PK; return that id.

    The PK is the idempotency key (§3.7): re-ingesting the same binding is a no-op-or-replace.
    """
    session_id = resolve_session_id(binding)
    minted = 1 if binding.minted_session_id is not None else 0
    conn.execute(
        """
        INSERT INTO session (
            session_id, provider, cli, run_id, cwd, workspace_slug, workspace_hash,
            native_session_id, minted, source_descriptor, started_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            provider          = excluded.provider,
            cli               = excluded.cli,
            run_id            = excluded.run_id,
            cwd               = excluded.cwd,
            workspace_slug    = excluded.workspace_slug,
            workspace_hash    = excluded.workspace_hash,
            native_session_id = excluded.native_session_id,
            minted            = excluded.minted,
            source_descriptor = excluded.source_descriptor,
            started_at        = excluded.started_at
        """,
        (
            session_id,
            binding.provider,
            binding.cli,
            binding.run_id,
            binding.cwd,
            binding.workspace_slug,
            binding.workspace_hash,
            binding.native_session_id,
            minted,
            binding.source_descriptor,
            binding.started_at,
        ),
    )
    return session_id
