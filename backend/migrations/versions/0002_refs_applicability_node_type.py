"""typed references, applicability qualifiers, node_type

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-03

Closes the gap between migration 0001 and the client's citation/traceability
requirements:

  - node_type          tell a whole Part from a single clause from a figure
  - internal_refs       resolved pointers to other nodes in this corpus
  - standard_refs       flagged hand-offs to Australian Standards etc.
  - building_classes / jurisdictions / climate_zones
                        structured applicability, for pre-filtering retrieval
  - applicability_note  the verbatim qualifier wording, for the LLM + citation

Safe to run non-concurrently: clause_chunks is still empty at this point.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clause_chunks",
        sa.Column(
            "node_type", sa.String(), nullable=False, server_default="clause"
        ),
    )

    # Typed references. cross_refs (raw parser output) stays as-is.
    op.add_column(
        "clause_chunks", sa.Column("internal_refs", postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        "clause_chunks", sa.Column("standard_refs", postgresql.JSONB(), nullable=True)
    )

    # Applicability qualifiers. NULL on an axis == no restriction on that axis.
    op.add_column(
        "clause_chunks",
        sa.Column("building_classes", postgresql.ARRAY(sa.String()), nullable=True),
    )
    op.add_column(
        "clause_chunks",
        sa.Column("jurisdictions", postgresql.ARRAY(sa.String()), nullable=True),
    )
    op.add_column(
        "clause_chunks",
        sa.Column("climate_zones", postgresql.ARRAY(sa.Integer()), nullable=True),
    )
    op.add_column(
        "clause_chunks", sa.Column("applicability_note", sa.Text(), nullable=True)
    )

    # GIN indexes so "clauses applying to Class 2 in NSW, climate zone 6" is a
    # fast array-containment pre-filter in front of the vector search.
    op.create_index(
        "ix_clause_chunks_building_classes",
        "clause_chunks",
        ["building_classes"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_clause_chunks_jurisdictions",
        "clause_chunks",
        ["jurisdictions"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_clause_chunks_climate_zones",
        "clause_chunks",
        ["climate_zones"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_clause_chunks_node_type", "clause_chunks", ["node_type"]
    )


def downgrade() -> None:
    op.drop_index("ix_clause_chunks_node_type", table_name="clause_chunks")
    op.drop_index("ix_clause_chunks_climate_zones", table_name="clause_chunks")
    op.drop_index("ix_clause_chunks_jurisdictions", table_name="clause_chunks")
    op.drop_index("ix_clause_chunks_building_classes", table_name="clause_chunks")
    op.drop_column("clause_chunks", "applicability_note")
    op.drop_column("clause_chunks", "climate_zones")
    op.drop_column("clause_chunks", "jurisdictions")
    op.drop_column("clause_chunks", "building_classes")
    op.drop_column("clause_chunks", "standard_refs")
    op.drop_column("clause_chunks", "internal_refs")
    op.drop_column("clause_chunks", "node_type")
