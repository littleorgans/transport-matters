"""Session correlation helpers: the frozen synthesis namespace, deterministic synth, and upsert.

The canonical ``SessionBinding`` now lives in ``index/adapters/base.py`` (§4.2) — slices 1/2
staged a copy here; this module keeps the read-back synthesis (``SESSION_NS`` /
``synth_session_id``) and the shared ``upsert_session`` that both the wire correlation (§7.2)
and the transcript adapters (§5/§7.3) use to land one ``session`` row keyed by ``session_id``.
"""

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

    from transport_matters.index.adapters.base import SessionBinding

# Frozen namespace for read-back session_id synthesis. Seeded into schema_meta.session_ns and
# gated on boot, so bumping it is a schema-version change (§3.2/§3.4).
SESSION_NS = uuid.UUID("a3f1c2d4-5e6b-4a7c-8d9e-0f1a2b3c4d5e")


def synth_session_id(run_id: str, provider: str, native_session_id: str) -> str:
    """Synthesize a read-back session_id (§3.4): ``uuid5`` over the frozen ``SESSION_NS``.

    Pure, so a read-back provider's wire correlation and transcript adapter independently compute
    the same value over the same ``(run_id, provider, native_session_id)`` and the pivot joins.
    """
    return str(uuid.uuid5(SESSION_NS, f"{run_id}|{provider}|{native_session_id}"))


def upsert_session(conn: sqlite3.Connection, binding: SessionBinding) -> str:
    """Upsert one ``session`` row keyed by the resolved ``session_id`` PK; return that id (§7.3).

    Both streams (wire + transcript) may upsert the same session. The nullable enrichment columns
    (``cli`` / ``native_session_id`` / ``source_descriptor``) are COALESCEd so a stream that does
    not know a value never clobbers one the other stream supplied.
    """
    conn.execute(
        """
        INSERT INTO session (
            session_id, provider, cli, run_id, cwd, workspace_slug, workspace_hash,
            native_session_id, minted, source_descriptor, started_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            provider          = excluded.provider,
            run_id            = excluded.run_id,
            cwd               = excluded.cwd,
            workspace_slug    = excluded.workspace_slug,
            workspace_hash    = excluded.workspace_hash,
            started_at        = excluded.started_at,
            minted            = excluded.minted,
            cli               = COALESCE(excluded.cli, session.cli),
            native_session_id = COALESCE(excluded.native_session_id, session.native_session_id),
            source_descriptor = COALESCE(excluded.source_descriptor, session.source_descriptor)
        """,
        (
            binding.session_id,
            binding.provider,
            binding.cli,
            binding.run_id,
            binding.cwd,
            binding.workspace_slug,
            binding.workspace_hash,
            binding.native_session_id,
            1 if binding.minted else 0,
            binding.source_descriptor,
            binding.started_at,
        ),
    )
    return binding.session_id
