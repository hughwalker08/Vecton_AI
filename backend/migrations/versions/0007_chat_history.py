"""chats and chat_messages for durable per-user chat history

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-21

Adds durable, per-user chat history, replacing the sidebar's previous
in-memory-only chat list (App.jsx's `chats` state, which reset on every
page refresh). This is a separate concern from
app/services/generation.py's MAX_HISTORY_MESSAGES -- that's how much of a
chat's history gets replayed to Gemini on each question; this is whether
the chat itself survives a refresh or a new device at all.

Same pattern as 0004's user_profiles, not 0006's compliance_feedback:
this is genuinely per-user private data, and the backend has no user auth
wired in (see 0006's docstring), so it's managed directly by the frontend
via the Supabase client, secured with Row Level Security rather than an
API route checking ownership itself.

chat_messages has no user_id of its own -- ownership is via its parent
chats row, so its RLS policies check auth.uid() through a subquery on
chats rather than comparing a column directly.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # gen_random_uuid() is core since Postgres 13, but Supabase projects
    # (and the pgvector/pgvector:pg17 image CI tests against) already have
    # pgcrypto available either way -- this just makes that explicit rather
    # than relying on it being there by default.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.chats (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

            user_id uuid NOT NULL
                REFERENCES auth.users(id)
                ON DELETE CASCADE,

            -- The question that started the chat, truncated -- same title
            -- App.jsx's old in-memory createChat() used to generate.
            title text NOT NULL,

            jurisdiction text NOT NULL
                CHECK (
                    jurisdiction IN (
                        'ACT',
                        'NSW',
                        'NT',
                        'QLD',
                        'SA',
                        'TAS',
                        'VIC',
                        'WA'
                    )
                ),

            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.chat_messages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

            chat_id uuid NOT NULL
                REFERENCES public.chats(id)
                ON DELETE CASCADE,

            role text NOT NULL
                CHECK (role IN ('user', 'assistant')),

            text text NOT NULL,

            -- ChatPage.jsx's Citation[] and abstained flag, so a reloaded
            -- chat shows the same sources and abstain note it did live --
            -- not re-derived, since retrieval could return something
            -- different by the time the chat is revisited.
            citations jsonb,
            abstained boolean NOT NULL DEFAULT false,

            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chats_user_id_created_at
        ON public.chats (user_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_chat_messages_chat_id_created_at
        ON public.chat_messages (chat_id, created_at ASC)
        """
    )

    op.execute("ALTER TABLE public.chats ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY")

    _policy(
        "chats", "Users can view their own chats", "SELECT",
        using="auth.uid() = user_id",
    )
    _policy(
        "chats", "Users can create their own chats", "INSERT",
        check="auth.uid() = user_id",
    )
    _policy(
        "chats", "Users can delete their own chats", "DELETE",
        using="auth.uid() = user_id",
    )

    _policy(
        "chat_messages", "Users can view messages in their own chats", "SELECT",
        using="""
            EXISTS (
                SELECT 1 FROM public.chats
                WHERE chats.id = chat_messages.chat_id
                  AND chats.user_id = auth.uid()
            )
        """,
    )
    _policy(
        "chat_messages", "Users can add messages to their own chats", "INSERT",
        check="""
            EXISTS (
                SELECT 1 FROM public.chats
                WHERE chats.id = chat_messages.chat_id
                  AND chats.user_id = auth.uid()
            )
        """,
    )


def _policy(table: str, name: str, command: str, using: str | None = None, check: str | None = None) -> None:
    """Idempotent CREATE POLICY, matching 0004_user_profiles.py's guard style."""
    clauses = []
    if using:
        clauses.append(f"USING ({using})")
    if check:
        clauses.append(f"WITH CHECK ({check})")
    clause_sql = "\n".join(clauses)

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = '{table}'
                  AND policyname = '{name}'
            ) THEN
                CREATE POLICY "{name}"
                ON public.{table}
                FOR {command}
                {clause_sql};
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.chat_messages")
    op.execute("DROP TABLE IF EXISTS public.chats")
