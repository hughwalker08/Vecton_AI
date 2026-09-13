"""
Tests for app.models.clause_chunk.ClauseChunk.

These inspect the SQLAlchemy table/column metadata directly rather than
hitting a real database -- no Postgres/pgvector connection is needed (that's
covered separately by the migration tests in a later phase). What's checked
here is exactly what the ingest pipeline (app/ingest/) and the API routes
rely on existing: the right columns, with the right types and constraints.
"""

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR

from app.core.config import settings
from app.models.clause_chunk import ClauseChunk


def test_table_name():
    assert ClauseChunk.__tablename__ == "clause_chunks"


def test_has_every_expected_column():
    columns = set(ClauseChunk.__table__.columns.keys())

    expected = {
        "id", "node_type", "clause_id", "heading", "doc", "hierarchy",
        "text", "defined_terms",
        "cross_refs", "internal_refs", "standard_refs", "image_refs",
        "building_classes", "jurisdictions", "climate_zones", "applicability_note",
        "source_url", "dataset_version", "retrieved_at", "created_at",
        "embedding", "text_tsv",
    }
    assert expected <= columns


def test_id_is_the_string_primary_key():
    col = ClauseChunk.__table__.c.id
    assert col.primary_key is True
    assert isinstance(col.type, String)


def test_node_type_is_required_and_defaults_to_clause():
    col = ClauseChunk.__table__.c.node_type
    assert col.nullable is False
    assert col.server_default.arg == "clause"


def test_text_is_required():
    col = ClauseChunk.__table__.c.text
    assert col.nullable is False
    assert isinstance(col.type, Text)


def test_clause_id_is_indexed_for_lookup():
    assert ClauseChunk.__table__.c.clause_id.index is True


def test_embedding_column_matches_configured_dimension():
    col = ClauseChunk.__table__.c.embedding
    assert isinstance(col.type, Vector)
    assert col.type.dim == settings.EMBEDDING_DIM


def test_reference_columns_are_json_or_jsonb():
    c = ClauseChunk.__table__.c
    assert isinstance(c.hierarchy.type, JSON)
    assert isinstance(c.defined_terms.type, JSON)
    assert isinstance(c.cross_refs.type, JSON)
    assert isinstance(c.internal_refs.type, JSONB)
    assert isinstance(c.standard_refs.type, JSONB)
    assert isinstance(c.image_refs.type, JSONB)


def test_applicability_columns_are_nullable_arrays():
    c = ClauseChunk.__table__.c
    for col in (c.building_classes, c.jurisdictions, c.climate_zones):
        assert isinstance(col.type, ARRAY)
        assert col.nullable is True  # NULL = "no restriction on this axis"


def test_created_at_has_a_server_side_now_default():
    col = ClauseChunk.__table__.c.created_at
    assert col.server_default is not None


def test_text_tsv_is_a_generated_tsvector_column_over_heading_and_text():
    """The auto-generated full-text column (migration 0003) -- this is the
    lexical half of hybrid_search() in services/retrieval.py."""
    col = ClauseChunk.__table__.c.text_tsv
    assert isinstance(col.type, TSVECTOR)
    assert col.computed is not None
    assert col.computed.persisted is True
    sql = str(col.computed.sqltext)
    assert "to_tsvector" in sql
    assert "heading" in sql
    assert "text" in sql
