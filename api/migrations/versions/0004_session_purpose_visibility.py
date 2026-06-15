"""session purpose visibility

Revision ID: 0004_session_purpose_visibility
Revises: 0003_event_dead_letter
Create Date: 2026-06-16 02:45:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "0004_session_purpose_visibility"
down_revision = "0003_event_dead_letter"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE "session"
            ADD COLUMN session_purpose text NOT NULL DEFAULT 'user',
            ADD COLUMN session_visibility text NOT NULL DEFAULT 'user_visible',
            ADD CONSTRAINT session_purpose_ck CHECK (
                session_purpose IN (
                    'user',
                    'continuation',
                    'internal_summary',
                    'internal_indexing',
                    'internal_eval',
                    'system_maintenance'
                )
            ),
            ADD CONSTRAINT session_visibility_ck CHECK (
                session_visibility IN ('user_visible', 'hidden', 'diagnostic')
            )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE "session"
            DROP CONSTRAINT session_visibility_ck,
            DROP CONSTRAINT session_purpose_ck,
            DROP COLUMN session_visibility,
            DROP COLUMN session_purpose
        """
    )
