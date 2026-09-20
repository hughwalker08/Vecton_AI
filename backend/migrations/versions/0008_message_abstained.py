"""add abstained flag to messages

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-21

ChatResponse.abstained (chat.py) distinguishes "no matching clause, didn't
call the LLM" from a normal answer -- the chat UI shows a different note for
it. 0007 didn't capture this, so a reloaded abstained message would render
as if the model had answered from a citation. No RLS change needed: the
existing messages policies already cover this column.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.messages
        ADD COLUMN IF NOT EXISTS abstained boolean NOT NULL DEFAULT false
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE public.messages
        DROP COLUMN IF EXISTS abstained
        """
    )
