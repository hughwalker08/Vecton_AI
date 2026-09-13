"""image_refs column

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-13

The ingest pipeline emits an `image_refs` list on every chunk that references
a figure -- 475 of the 2,788 distinct chunks carry one -- but there was no
column to put it in, so `app.ingest.load_db` would silently drop it.

Shape (mirrors app/ingest/figure_parser.py):
    [{"image_id": "<uuid>", "filename": "figure_11_2_2.svg",
      "caption": "Figure 11.2.2: Stair riser and going dimensions"}]

JSONB rather than JSON so the filename can be indexed later if figure lookups
need it; no index yet, since nothing queries on it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clause_chunks",
        sa.Column("image_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clause_chunks", "image_refs")
