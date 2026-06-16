"""session template provenance

Revision ID: 0005_session_template_provenance
Revises: 0004_session_purpose_visibility
Create Date: 2026-06-16 09:30:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "0005_session_template_provenance"
down_revision = "0004_session_purpose_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE "session" ADD COLUMN template_provenance jsonb')


def downgrade() -> None:
    op.execute('ALTER TABLE "session" DROP COLUMN template_provenance')
