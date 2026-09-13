"""
SQLAlchemy model for a clause chunk: one node of the NCC 2025 Vol Two /
ABCB Housing Provisions corpus (or a parsed user upload).

Schema history:
  0001  base table + pgvector `embedding` column + hnsw cosine index
  0002  typed references, applicability qualifiers, node_type
        (covers the client's citation/traceability requirements)
  0003  text_tsv generated column + GIN index (lexical half of retrieval)
  0004  user_profiles table (separate; does not touch this model)
  0005  image_refs

Embedding: Gemini `text-embedding-004`, 768-dim (settings.EMBEDDING_DIM).
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column, Computed, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.sql import func

from app.core.config import settings
from app.db.session import Base


class ClauseChunk(Base):
    __tablename__ = "clause_chunks"

    id = Column(String, primary_key=True)  # uuid string

    # --- what this node is ---
    # part | section | clause | subclause | figure | table | note
    node_type = Column(String, nullable=False, server_default="clause")
    clause_id = Column(String, index=True)  # real NCC id, e.g. "H1D4", "10.8"
    heading = Column(String)
    doc = Column(String)  # "NCC 2025 Volume Two" | "ABCB Housing Provisions 2022"
    hierarchy = Column(JSON)  # path above this node, e.g. ["Volume Two", "Section H", "Part H1", "H1D4"]

    # --- the text the user reads / that gets embedded ---
    text = Column(Text, nullable=False)
    defined_terms = Column(JSON)

    # --- references out of this clause ---
    # Raw strings straight from the parser, kept for debugging/traceability.
    cross_refs = Column(JSON)  # e.g. ["3.2.5", "AS 3600"]
    # Pointers to other nodes in THIS corpus. chunk_id filled in by the
    # post-ingest resolution pass; null until then.
    # [{"clause_id": "3.2.5.1", "chunk_id": "<uuid|null>"}]
    internal_refs = Column(JSONB)
    # Hand-offs to documents OUTSIDE the corpus (Australian Standards etc.).
    # [{"standard": "AS 3600", "clause": "8.1.3", "title": "Concrete structures"}]
    # Loaded from the ingest pipeline's `external_refs` -- same data; the names
    # differ because ingest also emits non-standard kinds (vol1, vol3, housing,
    # livable).
    standard_refs = Column(JSONB)

    # Figures this chunk references, from the ingest pipeline (migration 0005).
    # [{"image_id": "<uuid>", "filename": "figure_11_2_2.svg", "caption": "..."}]
    image_refs = Column(JSONB)

    # --- applicability qualifiers ---
    # NULL means "no restriction on this axis" (applies to all).
    building_classes = Column(ARRAY(String))    # e.g. {"1a", "1b"}
    jurisdictions = Column(ARRAY(String))       # e.g. {"NSW"}; NULL = national
    climate_zones = Column(ARRAY(Integer))      # e.g. {6, 7, 8}
    applicability_note = Column(Text)           # verbatim qualifier wording

    # --- provenance ---
    source_url = Column(String)
    dataset_version = Column(String)
    retrieved_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    # --- retrieval ---
    # Dense: Gemini text-embedding-004. Lexical: Postgres full-text over
    # heading + text, maintained by the DB (Computed / STORED generated column).
    embedding = Column(Vector(settings.EMBEDDING_DIM))
    text_tsv = Column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(heading, '') || ' ' || text)",
            persisted=True,
        ),
    )
