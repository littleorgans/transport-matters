"""event tier 1 indexes

Revision ID: 0002_event_tier1_indexes
Revises: 0001_session_store
Create Date: 2026-06-09 01:05:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "0002_event_tier1_indexes"
down_revision = "0001_session_store"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE INDEX event_raw_gin ON "event" USING gin (raw jsonb_path_ops)')
    op.execute(
        """
        CREATE INDEX event_session_raw_type_expr_ix
        ON "event" (session_id, (raw->>'type'), (raw->>'subtype'), seq)
        """
    )
    op.execute(
        """
        CREATE INDEX event_session_attachment_type_expr_ix
        ON "event" (session_id, ((raw->'attachment'->>'type')), seq)
        WHERE raw ? 'attachment'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX event_session_attachment_type_expr_ix")
    op.execute("DROP INDEX event_session_raw_type_expr_ix")
    op.execute("DROP INDEX event_raw_gin")
