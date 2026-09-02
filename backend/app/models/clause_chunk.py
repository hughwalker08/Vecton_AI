"""
SQLAlchemy model skeleton for a clause chunk (NCC / ABCB corpus, or a
parsed user upload). Matches the metadata structure from the planning doc.

Not yet wired to a migration - fields/types are indicative and will need
the pgvector column type added once the embedding model + dimension are
decided (BGE-M3 vs Gemini).
"""

from sqlalchemy import Column, String, Text, JSON, DateTime
from sqlalchemy.sql import func

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

    # TODO: add pgvector embedding column once embedding model is chosen,
    # e.g. embedding = Column(Vector(dim)) via the `pgvector.sqlalchemy` type.
