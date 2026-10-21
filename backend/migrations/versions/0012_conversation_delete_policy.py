"""DELETE policy on conversations so users can delete past chats

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-22

0007 only granted SELECT/INSERT on conversations, so a delete from the
frontend's Supabase client was silently filtered to zero rows by RLS. This
adds the owner-scoped DELETE policy (same shape as 0009/0010's). messages
needs no policy of its own: messages.conversation_id is ON DELETE CASCADE,
and the cascade isn't subject to the deleting user's RLS.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'public' AND tablename = 'conversations'
                  AND policyname = 'Users can delete their own conversations'
            ) THEN
                CREATE POLICY "Users can delete their own conversations"
                ON public.conversations
                FOR DELETE
                USING (auth.uid() = user_id);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY IF EXISTS "Users can delete their own conversations"
        ON public.conversations
        """
    )
