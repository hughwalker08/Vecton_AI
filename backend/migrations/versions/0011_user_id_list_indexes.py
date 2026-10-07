"""user_id indexes for the frontend's per-user list queries

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-08

The sidebar loads (App.jsx's loadChats/loadProjects/loadDocuments) read
conversations, projects and folders filtered to the signed-in user by RLS
(auth.uid() = user_id) and sorted by a timestamp. 0007/0009/0010 only
indexed project_id on these three, so each load was a sequential scan over
every user's rows plus a sort -- cost growing with total users, not with
the caller's own row count. documents already had this shape of index
(0009's ix_documents_user_id_created_at).

Each index matches its query's filter + ORDER BY, so Postgres reads just the
caller's rows, already in order, with no sort step.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conversations_user_id_updated_at
        ON public.conversations (user_id, updated_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_projects_user_id_created_at
        ON public.projects (user_id, created_at)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_folders_user_id_created_at
        ON public.folders (user_id, created_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.ix_folders_user_id_created_at")
    op.execute("DROP INDEX IF EXISTS public.ix_projects_user_id_created_at")
    op.execute("DROP INDEX IF EXISTS public.ix_conversations_user_id_updated_at")
