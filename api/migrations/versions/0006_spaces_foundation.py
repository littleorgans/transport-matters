from __future__ import annotations

from alembic import op

revision = "0006_spaces_foundation"
down_revision = "0005_session_template_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE space (
            space_id uuid PRIMARY KEY,
            owner text NOT NULL DEFAULT 'local',
            name text NOT NULL,
            archived boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE space_git_identity (
            space_id uuid NOT NULL,
            repo_instance_key text NOT NULL,
            git_common_dir text NOT NULL,
            detected_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (space_id, repo_instance_key),
            CONSTRAINT space_git_identity_space_fk
                FOREIGN KEY (space_id) REFERENCES space(space_id) ON DELETE CASCADE,
            CONSTRAINT space_git_identity_repo_instance_key_uq UNIQUE (repo_instance_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE space_worktree (
            worktree_id uuid PRIMARY KEY,
            space_id uuid NOT NULL,
            owner text NOT NULL DEFAULT 'local',
            path text,
            workspace_slug text NOT NULL,
            workspace_hash text NOT NULL,
            branch_name text,
            head_oid text,
            is_primary boolean NOT NULL DEFAULT false,
            missing boolean NOT NULL DEFAULT false,
            archived boolean NOT NULL DEFAULT false,
            detected_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT space_worktree_space_fk
                FOREIGN KEY (space_id) REFERENCES space(space_id) ON DELETE CASCADE,
            CONSTRAINT space_worktree_workspace_uq UNIQUE (owner, workspace_slug, workspace_hash),
            CONSTRAINT space_worktree_path_uq UNIQUE (owner, path)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE canvas (
            canvas_id uuid PRIMARY KEY,
            space_id uuid NOT NULL,
            owner text NOT NULL DEFAULT 'local',
            name text NOT NULL,
            default_worktree_id uuid,
            layout jsonb NOT NULL DEFAULT '{}'::jsonb,
            layout_version integer NOT NULL DEFAULT 1,
            archived boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT canvas_space_fk
                FOREIGN KEY (space_id) REFERENCES space(space_id) ON DELETE CASCADE,
            CONSTRAINT canvas_default_worktree_fk
                FOREIGN KEY (default_worktree_id)
                REFERENCES space_worktree(worktree_id)
                ON DELETE SET NULL
        )
        """
    )
    op.execute(
        """
        ALTER TABLE "session"
            ADD COLUMN space_id uuid,
            ADD COLUMN worktree_id uuid
        """
    )
    op.execute(
        """
        CREATE INDEX session_space_ix
        ON "session" (owner, space_id, started_at DESC)
        WHERE space_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX session_worktree_ix
        ON "session" (owner, worktree_id, started_at DESC)
        WHERE worktree_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX session_worktree_ix")
    op.execute("DROP INDEX session_space_ix")
    op.execute(
        """
        ALTER TABLE "session"
            DROP COLUMN worktree_id,
            DROP COLUMN space_id
        """
    )
    op.execute("DROP TABLE canvas")
    op.execute("DROP TABLE space_worktree")
    op.execute("DROP TABLE space_git_identity")
    op.execute("DROP TABLE space")
