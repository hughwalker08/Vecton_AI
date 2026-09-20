"""conversations and messages for persisted chat history

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-21

Chat history previously lived only in the frontend's React state (see
app/api/routes/chat.py's docstring) -- a refresh, closed tab, or new device
lost it. This adds two Supabase-Auth-scoped tables so the chat sidebar and
a chat's messages survive across sessions, mirroring 0004's user_profiles
pattern (RLS keyed off auth.uid(), read/written directly by the frontend's
Supabase client -- the FastAPI backend stays stateless and is never on the
path for this).

`messages.user_id` is denormalized (also derivable via a join through
conversations) so its RLS policies don't need a subquery per row.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.conversations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL
                REFERENCES auth.users(id)
                ON DELETE CASCADE,

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

            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.messages (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            conversation_id uuid NOT NULL
                REFERENCES public.conversations(id)
                ON DELETE CASCADE,
            user_id uuid NOT NULL
                REFERENCES auth.users(id)
                ON DELETE CASCADE,

            role text NOT NULL CHECK (role IN ('user', 'assistant')),
            text text NOT NULL,
            -- Citation objects from ChatResponse, verbatim -- null for user
            -- messages and for assistant messages with no matched clauses.
            citations jsonb,
            attachment_name text,
            is_error boolean NOT NULL DEFAULT false,

            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_messages_conversation_id_created_at
        ON public.messages (conversation_id, created_at)
        """
    )

    op.execute(
        """
        ALTER TABLE public.conversations
        ENABLE ROW LEVEL SECURITY
        """
    )
    op.execute(
        """
        ALTER TABLE public.messages
        ENABLE ROW LEVEL SECURITY
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'public' AND tablename = 'conversations'
                  AND policyname = 'Users can view their own conversations'
            ) THEN
                CREATE POLICY "Users can view their own conversations"
                ON public.conversations
                FOR SELECT
                USING (auth.uid() = user_id);
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'public' AND tablename = 'conversations'
                  AND policyname = 'Users can create their own conversations'
            ) THEN
                CREATE POLICY "Users can create their own conversations"
                ON public.conversations
                FOR INSERT
                WITH CHECK (auth.uid() = user_id);
            END IF;
        END
        $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'public' AND tablename = 'messages'
                  AND policyname = 'Users can view their own messages'
            ) THEN
                CREATE POLICY "Users can view their own messages"
                ON public.messages
                FOR SELECT
                USING (auth.uid() = user_id);
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_policies
                WHERE schemaname = 'public' AND tablename = 'messages'
                  AND policyname = 'Users can create their own messages'
            ) THEN
                CREATE POLICY "Users can create their own messages"
                ON public.messages
                FOR INSERT
                WITH CHECK (auth.uid() = user_id);
            END IF;
        END
        $$;
        """
    )

    # Bumps the parent conversation's updated_at whenever a message is added,
    # so "Earlier questions" can sort by recency without the frontend making
    # a second write. SECURITY DEFINER (running as the function owner, which
    # owns both tables) so it isn't blocked by conversations' own RLS, which
    # only grants SELECT/INSERT to the owning user, not UPDATE.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.touch_conversation_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = public
        AS $$
        BEGIN
            UPDATE public.conversations
            SET updated_at = now()
            WHERE id = NEW.conversation_id;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS messages_touch_conversation ON public.messages
        """
    )
    op.execute(
        """
        CREATE TRIGGER messages_touch_conversation
        AFTER INSERT ON public.messages
        FOR EACH ROW
        EXECUTE FUNCTION public.touch_conversation_updated_at()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS messages_touch_conversation ON public.messages
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS public.touch_conversation_updated_at()
        """
    )
    op.execute(
        """
        DROP TABLE IF EXISTS public.messages
        """
    )
    op.execute(
        """
        DROP TABLE IF EXISTS public.conversations
        """
    )
