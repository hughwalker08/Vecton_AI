"""folders and documents for persisted project files

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-21

Uploaded documents (Upload page / "Project files") previously lived only in
React state -- like chat history before migration 0007, a refresh wiped
them, and nothing was ever kept server-side (the backend processes each
upload in-memory and returns extracted text/image descriptions without
persisting anything). This adds folders + documents, RLS-scoped to
auth.uid() like conversations/messages, so the file list and its folder
organisation survive a refresh.

Only metadata + the already-extracted text is stored here (documents.text),
not the original file bytes -- there's no Supabase Storage integration in
this project, and the chat-attachment feature already treats extracted
text, not the raw file, as the thing worth keeping (see
messages.attachment_name). Re-running a compliance check after a refresh
works from the stored text; re-viewing the original PDF/DOCX itself does
not, unless/until a Storage bucket is added separately.

Unlike conversations/messages, these two need UPDATE and DELETE policies
too: renaming a folder, moving a document between folders, and removing
either are all done directly by the frontend's Supabase client, the same
way user_profiles' own update works.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.folders (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL
                REFERENCES auth.users(id)
                ON DELETE CASCADE,

            name text NOT NULL,

            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.documents (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL
                REFERENCES auth.users(id)
                ON DELETE CASCADE,
            -- NULL = unfiled. A deleted folder un-files its documents rather
            -- than deleting them.
            folder_id uuid
                REFERENCES public.folders(id)
                ON DELETE SET NULL,

            name text NOT NULL,
            size bigint,
            status text NOT NULL DEFAULT 'done'
                CHECK (status IN ('uploading', 'done', 'error')),
            -- Upload status line (e.g. "processed 2 image(s) from plan.pdf")
            -- or the error message when status = 'error'.
            detail text,
            -- services/document_text.py's extraction, same field name and
            -- meaning as messages.text carries for a chat attachment.
            text text,

            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_documents_user_id_created_at
        ON public.documents (user_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_documents_folder_id
        ON public.documents (folder_id)
        """
    )

    op.execute("ALTER TABLE public.folders ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY")

    for table, cmd in [
        ("folders", "SELECT"),
        ("folders", "INSERT"),
        ("folders", "UPDATE"),
        ("folders", "DELETE"),
        ("documents", "SELECT"),
        ("documents", "INSERT"),
        ("documents", "UPDATE"),
        ("documents", "DELETE"),
    ]:
        policy = f"Users can {cmd.lower()} their own {table}"
        using_clause = "USING (auth.uid() = user_id)" if cmd != "INSERT" else ""
        check_clause = (
            "WITH CHECK (auth.uid() = user_id)" if cmd in ("INSERT", "UPDATE") else ""
        )
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_policies
                    WHERE schemaname = 'public' AND tablename = '{table}'
                      AND policyname = '{policy}'
                ) THEN
                    CREATE POLICY "{policy}"
                    ON public.{table}
                    FOR {cmd}
                    {using_clause}
                    {check_clause};
                END IF;
            END
            $$;
            """
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.documents")
    op.execute("DROP TABLE IF EXISTS public.folders")
