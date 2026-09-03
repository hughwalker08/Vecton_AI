"""
SQLAlchemy model skeleton for a clause chunk (NCC / ABCB corpus, or a
parsed user upload). Matches the metadata structure from the planning doc.

Embedding model is decided: Gemini `text-embedding-004`, 768-dim
(settings.EMBEDDING_DIM), so the pgvector column dimension is fixed below.
Still not wired to a migration - add an Alembic migration that also runs
`CREATE EXTENSION IF NOT EXISTS vector` and creates an ANN index
(hnsw / ivfflat) on `embedding`.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Text, JSON, DateTime
from sqlalchemy.sql import func

from app.core.config import settings
from app.db.session import Base


class ClauseChunk(Base):
    __tablename__ = "clause_chunks"

    id = Column(String, primary_key=True)  # e.g. uuid
    text = Column(Text, nullable=False)
    clause_id = Column(String, index=True)
    hierarchy = Column(JSON)  # e.g. ["Volume Two", "Part 3.7", "3.7.1", "3.7.1.2"]
    heading = Column(String)
    doc = Column(String)  # e.g. "NCC 2025 Volume Two"
    cross_refs = Column(JSON)  # outward references, e.g. ["3.2.5", "AS 3600"]
    defined_terms = Column(JSON)
    source_url = Column(String)
    dataset_version = Column(String)
    retrieved_at = Column(DateTime)
    created_at = Column(DateTime, server_default=func.now())

    # Gemini text-embedding-004 output. Dimension must match settings.EMBEDDING_DIM.
    embedding = Column(Vector(settings.EMBEDDING_DIM))

    # TODO (migration): tsvector column + GIN index on `text` for the BM25 side
    # of hybrid retrieval, and an hnsw/ivfflat index on `embedding`.
