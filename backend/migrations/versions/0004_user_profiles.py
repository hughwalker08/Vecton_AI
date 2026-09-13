"""user profiles for auth onboarding and jurisdiction routing

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-12

Adds a user profile table linked to Supabase Auth.

The profile stores the user's selected Australian jurisdiction so that
chat retrieval can route queries to national clauses plus the clauses
specific to that state or territory.

Row Level Security ensures authenticated users can only read or modify
their own profile.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS public.user_profiles (
            id uuid PRIMARY KEY
                REFERENCES auth.users(id)
                ON DELETE CASCADE,

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
        ALTER TABLE public.user_profiles
        ENABLE ROW LEVEL SECURITY
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = 'user_profiles'
                  AND policyname = 'Users can view their own profile'
            ) THEN
                CREATE POLICY "Users can view their own profile"
                ON public.user_profiles
                FOR SELECT
                USING (auth.uid() = id);
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
                SELECT 1
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = 'user_profiles'
                  AND policyname = 'Users can create their own profile'
            ) THEN
                CREATE POLICY "Users can create their own profile"
                ON public.user_profiles
                FOR INSERT
                WITH CHECK (auth.uid() = id);
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
                SELECT 1
                FROM pg_policies
                WHERE schemaname = 'public'
                  AND tablename = 'user_profiles'
                  AND policyname = 'Users can update their own profile'
            ) THEN
                CREATE POLICY "Users can update their own profile"
                ON public.user_profiles
                FOR UPDATE
                USING (auth.uid() = id)
                WITH CHECK (auth.uid() = id);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS public.user_profiles
        """
    )