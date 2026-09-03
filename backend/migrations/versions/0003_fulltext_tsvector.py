"""full-text search: text_tsv generated column + GIN index

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-03

Adds the lexical (BM25-style) half of hybrid retrieval:

  - text_tsv : a STORED generated tsvector over heading + text, so Postgres
               keeps it in sync automatically on every insert/update.
  - GIN index on text_tsv for fast `@@ plainto_tsquery(...)` matching.

Query side (retrieval.hybrid_search) fuses:
    ORDER BY embedding <=> :qvec            -- dense
    ts_rank_cd(text_tsv, plainto_tsquery('english', :q))  -- lexical
via Reciprocal Rank Fusion.

Safe non-concurrently: clause_chunks is still empty.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE clause_chunks
        ADD COLUMN text_tsv tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(heading, '') || ' ' || text)
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_clause_chunks_text_tsv "
        "ON clause_chunks USING gin (text_tsv)"
    )


def downgrade() -> None:
    op.drop_index("ix_clause_chunks_text_tsv", table_name="clause_chunks")
    op.drop_column("clause_chunks", "text_tsv")
