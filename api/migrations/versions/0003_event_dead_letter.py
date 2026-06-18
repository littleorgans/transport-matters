"""event dead letter

Revision ID: 0003_event_dead_letter
Revises: 0002_event_tier1_indexes
Create Date: 2026-06-14 03:30:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "0003_event_dead_letter"
down_revision = "0002_event_tier1_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE event_dead_letter (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            session_id text NOT NULL,
            seq integer,
            scope text NOT NULL DEFAULT 'record',
            run_id text NOT NULL,
            native_session_id text,
            provider text,
            harness text,
            source_path text,
            source_line integer,
            event_kind text,
            byte_start bigint NOT NULL,
            byte_end bigint NOT NULL,
            error_sqlstate text,
            error_class text,
            error_message text,
            raw_excerpt bytea,
            raw_sha256 text,
            raw_byte_len bigint,
            attempts integer NOT NULL DEFAULT 1,
            first_failed_at timestamptz NOT NULL DEFAULT now(),
            quarantined_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT event_dead_letter_scope_ck CHECK (scope IN ('record', 'window')),
            CONSTRAINT event_dead_letter_span_ck CHECK (byte_end > byte_start)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX event_dead_letter_span_uq
        ON event_dead_letter (session_id, byte_start, byte_end)
        """
    )
    op.execute(
        """
        CREATE INDEX event_dead_letter_run_ix
        ON event_dead_letter (run_id, native_session_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX event_dead_letter_run_ix")
    op.execute("DROP INDEX event_dead_letter_span_uq")
    op.execute("DROP TABLE event_dead_letter")
