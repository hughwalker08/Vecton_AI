"""initial schema: pgvector extension + clause_chunks table

Revision ID: 0001
Revises:
Create Date: 2026-09-03

Creates:
  - the `vector` extension (pgvector)
  - the `clause_chunks` table (NCC/ABCB corpus + parsed user uploads)
  - a btree index on clause_id
  - an HNSW index on the 768-dim Gemini embedding for cosine similarity search

Note: EMBEDDING_DIM is hard-coded to 768 here on purpose. A migration is a
frozen snapshot of a schema change; if the embedding model (and therefore the
dimension) ever changes, that is a NEW migration, not an edit to this one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    # Requires elevated privileges. Supabase's `postgres` role has them.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "clause_chunks",
        sa.Column("id", sa.String(), primary_key=True),  # uuid string
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("clause_id", sa.String(), nullable=True),
        sa.Column("hierarchy", sa.JSON(), nullable=True),
        sa.Column("heading", sa.String(), nullable=True),
        sa.Column("doc", sa.String(), nullable=True),
        sa.Column("cross_refs", sa.JSON(), nullable=True),
        sa.Column("defined_terms", sa.JSON(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("dataset_version", sa.String(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=True,
        ),
        # Gemini text-embedding-004 output. Nullable so a row can exist before
        # it has been embedded; the backfill job fills it in.
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    )

    op.create_index(
        "ix_clause_chunks_clause_id", "clause_chunks", ["clause_id"]
    )

    # Approximate-nearest-neighbour index for cosine similarity (`<=>`).
    # HNSW: good recall, builds fine on an empty table. Bump maintenance memory
    # for the build; harmless on an empty table, matters after the backfill if
    # this index is ever rebuilt.
    op.execute("SET maintenance_work_mem = '512MB'")
    op.execute(
        "CREATE INDEX ix_clause_chunks_embedding ON clause_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_index("ix_clause_chunks_embedding", table_name="clause_chunks")
    op.drop_index("ix_clause_chunks_clause_id", table_name="clause_chunks")
    op.drop_table("clause_chunks")
    # The `vector` extension is intentionally left installed — other tables may
    # come to depend on it, and dropping it is rarely what you want on rollback.
