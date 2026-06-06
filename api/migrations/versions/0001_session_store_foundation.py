"""session store foundation

Revision ID: 0001_session_store
Revises:
Create Date: 2026-06-06 07:20:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "0001_session_store"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE "session" (
            session_id text PRIMARY KEY,
            provider text NOT NULL,
            cli text,
            run_id text NOT NULL,
            cwd text NOT NULL DEFAULT '',
            workspace_slug text NOT NULL,
            workspace_hash text NOT NULL,
            native_session_id text,
            minted boolean NOT NULL DEFAULT false,
            source_descriptor jsonb,
            home_dir text,
            owner text NOT NULL DEFAULT 'local',
            status text NOT NULL DEFAULT 'active',
            title text,
            parent_session_id text REFERENCES "session"(session_id),
            forked_at_seq integer,
            started_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT session_status_ck CHECK (status IN ('active', 'completed', 'archived')),
            CONSTRAINT session_fork_ck CHECK ((parent_session_id IS NULL) = (forked_at_seq IS NULL))
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX session_native_uq
        ON "session" (owner, run_id, provider, native_session_id)
        WHERE native_session_id IS NOT NULL
        """
    )
    op.execute('CREATE INDEX session_browse_ix ON "session" (workspace_hash, started_at DESC)')
    op.execute('CREATE INDEX session_owner_ix ON "session" (owner, started_at DESC)')
    op.execute('CREATE INDEX session_parent_ix ON "session" (parent_session_id)')
    op.execute(
        """
        CREATE TABLE "event" (
            session_id text NOT NULL REFERENCES "session"(session_id) ON DELETE CASCADE,
            seq integer NOT NULL,
            kind text NOT NULL DEFAULT 'turn',
            native_turn_id text,
            parent_native_id text,
            parent_seq integer,
            run_id text NOT NULL,
            provider text NOT NULL,
            cli text NOT NULL,
            role text,
            is_sidechain boolean NOT NULL DEFAULT false,
            ts timestamptz,
            model text,
            raw jsonb NOT NULL,
            ir jsonb,
            source_path text,
            source_line integer,
            search_text text,
            content_tsv tsvector GENERATED ALWAYS AS (
                to_tsvector('english', coalesce(search_text, ''))
            ) STORED,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (session_id, seq),
            CONSTRAINT event_kind_ck CHECK (kind IN ('turn', 'meta'))
        )
        """
    )
    op.execute('CREATE INDEX event_native_ix ON "event" (session_id, native_turn_id)')
    op.execute('CREATE INDEX event_ir_gin ON "event" USING gin (ir)')
    op.execute('CREATE INDEX event_fts_gin ON "event" USING gin (content_tsv)')
    op.execute(
        """
        CREATE TABLE artifact (
            hash text PRIMARY KEY,
            media_type text,
            size_bytes bigint NOT NULL,
            bytes bytea NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE event_artifact (
            session_id text NOT NULL,
            seq integer NOT NULL,
            artifact_hash text NOT NULL REFERENCES artifact(hash),
            ref jsonb,
            PRIMARY KEY (session_id, seq, artifact_hash),
            FOREIGN KEY (session_id, seq) REFERENCES "event"(session_id, seq) ON DELETE CASCADE
        )
        """
    )


def downgrade() -> None:
    raise RuntimeError("session store migrations are forward only")
