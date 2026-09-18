"""compliance_feedback table

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-18

Lets a reviewer flag a compliance_analysis finding (see
app/services/compliance_analysis.py) as wrongly classified.

Not tied to auth, unlike 0004's user_profiles: the API routes have no
per-user login wired in yet, so this is a flat, reviewable log of flags
rather than a per-user table -- keyed by which clause + query the finding
came from and what status was reported.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compliance_feedback",
        sa.Column("id", sa.String(), primary_key=True),  # uuid string
        sa.Column("clause_id", sa.String(), nullable=False),
        sa.Column("doc", sa.String(), nullable=True),
        # The analyse_document() query that produced the flagged finding, kept
        # so a reviewer can see what the analysis run was even about.
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("reported_status", sa.String(), nullable=False),
        sa.Column("corrected_status", sa.String(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_compliance_feedback_clause_id", "compliance_feedback", ["clause_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_compliance_feedback_clause_id", table_name="compliance_feedback")
    op.drop_table("compliance_feedback")
