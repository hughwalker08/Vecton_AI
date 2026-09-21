"""projects, grouping chats and folders

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-21

Adds a `projects` table (RLS-scoped like everything else since 0004) as an
optional extra organising layer above conversations and folders/documents --
a chat or a folder can be tagged with a project, or left unassigned, same as
a document can be left out of any folder. Deleting a project un-assigns its
chats/folders/documents (ON DELETE SET NULL) rather than deleting them,
mirroring 0009's folder-delete behaviour.

`documents.project_id` (not just `folders.project_id`) exists so a file
dropped at a project's root -- no folder open -- has somewhere to live
without forcing a folder to be created first.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.projects (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL
                REFERENCES auth.users(id)
                ON DELETE CASCADE,

            name text NOT NULL,

            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY")

    for cmd in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
        policy = f"Users can {cmd.lower()} their own projects"
        using_clause = "USING (auth.uid() = user_id)" if cmd != "INSERT" else ""
        check_clause = "WITH CHECK (auth.uid() = user_id)" if cmd in ("INSERT", "UPDATE") else ""
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE schemaname = 'public' AND tablename = 'projects'
                      AND policyname = '{policy}'
                ) THEN
                    CREATE POLICY "{policy}"
                    ON public.projects
                    FOR {cmd}
                    {using_clause}
                    {check_clause};
                END IF;
            END
            $$;
            """
        )

    op.execute(
        """
        ALTER TABLE public.conversations
        ADD COLUMN IF NOT EXISTS project_id uuid
            REFERENCES public.projects(id)
            ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE public.folders
        ADD COLUMN IF NOT EXISTS project_id uuid
            REFERENCES public.projects(id)
            ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE public.documents
        ADD COLUMN IF NOT EXISTS project_id uuid
            REFERENCES public.projects(id)
            ON DELETE SET NULL
        """
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversations_project_id ON public.conversations (project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_folders_project_id ON public.folders (project_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_documents_project_id ON public.documents (project_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE public.documents DROP COLUMN IF EXISTS project_id")
    op.execute("ALTER TABLE public.folders DROP COLUMN IF EXISTS project_id")
    op.execute("ALTER TABLE public.conversations DROP COLUMN IF EXISTS project_id")
    op.execute("DROP TABLE IF EXISTS public.projects")
