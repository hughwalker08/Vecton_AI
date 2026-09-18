"""
Tests for POST /api/compliance/analyse and the /feedback log.

app.services.compliance_analysis.analyse_document is imported by name into
app.api.routes.compliance's own namespace, so it's monkeypatched there
directly for the /analyse tests -- no real Gemini calls happen in this file.

The /feedback tests exercise the real compliance_feedback table, but against
an in-memory SQLite database (app.db.session.get_db is overridden), not a
real Postgres -- fine here since that table has no Postgres-specific column
types, unlike clause_chunks (pgvector) or user_profiles (Supabase auth/RLS).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import compliance
from app.db.session import get_db
from app.main import app
from app.models.compliance_feedback import ComplianceFeedback
from app.services.compliance_analysis import ComplianceFinding, ComplianceReport


@pytest.fixture()
def feedback_db():
    """Overrides get_db with an isolated in-memory SQLite session per test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ComplianceFeedback.__table__.create(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


def _finding(**overrides):
    base = dict(
        clause_id="H1D4",
        doc="NCC 2025 Volume Two",
        status="addressed",
        explanation="The document specifies footing depths that meet H1D4.",
        heading="Footings",
        evidence="Footings shall be 600mm deep.",
        source_url="https://ncc.abcb.gov.au/H1D4",
    )
    return ComplianceFinding(**{**base, **overrides})


def _request(**overrides):
    base = dict(document_text="Footings shall be 600mm deep.", query="footing requirements")
    return {**base, **overrides}


def test_analyse_empty_document_text_returns_400(client):
    response = client.post("/api/compliance/analyse", json=_request(document_text="   "))

    assert response.status_code == 400


def test_analyse_empty_query_returns_400(client):
    response = client.post("/api/compliance/analyse", json=_request(query="   "))

    assert response.status_code == 400


def test_analyse_invalid_jurisdiction_is_rejected(client):
    response = client.post("/api/compliance/analyse", json=_request(jurisdiction="XX"))

    assert response.status_code == 422


def test_analyse_success_returns_findings_and_counts(client, monkeypatch):
    report = ComplianceReport(
        query="footing requirements",
        jurisdiction="NSW",
        findings=[_finding(), _finding(clause_id="H1D5", status="missing", evidence=None)],
    )
    monkeypatch.setattr(compliance, "analyse_document", lambda *a, **k: report)

    response = client.post("/api/compliance/analyse", json=_request(jurisdiction="NSW"))

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "footing requirements"
    assert body["jurisdiction"] == "NSW"
    assert len(body["findings"]) == 2
    assert body["findings"][0]["status"] == "addressed"
    assert body["findings"][1] == {
        "clause_id": "H1D5",
        "doc": "NCC 2025 Volume Two",
        "status": "missing",
        "explanation": "The document specifies footing depths that meet H1D4.",
        "heading": "Footings",
        "evidence": None,
        "source_url": "https://ncc.abcb.gov.au/H1D4",
    }
    assert body["counts"] == {
        "addressed": 1,
        "missing": 1,
        "contradicted": 0,
        "needs_review": 0,
    }


def test_analyse_no_applicable_clauses_returns_empty_report(client, monkeypatch):
    monkeypatch.setattr(
        compliance,
        "analyse_document",
        lambda *a, **k: ComplianceReport(query="footing requirements", jurisdiction=None),
    )

    response = client.post("/api/compliance/analyse", json=_request())

    body = response.json()
    assert response.status_code == 200
    assert body["findings"] == []
    assert body["counts"] == {
        "addressed": 0,
        "missing": 0,
        "contradicted": 0,
        "needs_review": 0,
    }


def test_analyse_quota_exceeded_maps_to_429(client, monkeypatch):
    def _raise(*a, **k):
        raise compliance.AnalysisQuotaExceeded("daily quota used up")

    monkeypatch.setattr(compliance, "analyse_document", _raise)

    response = client.post("/api/compliance/analyse", json=_request())

    assert response.status_code == 429
    assert "quota" in response.json()["detail"]


def test_analyse_embedding_quota_exceeded_maps_to_429(client, monkeypatch):
    def _raise(*a, **k):
        raise compliance.EmbeddingQuotaExceeded("daily quota used up")

    monkeypatch.setattr(compliance, "analyse_document", _raise)

    response = client.post("/api/compliance/analyse", json=_request())

    assert response.status_code == 429


def test_analyse_error_maps_to_502(client, monkeypatch):
    def _raise(*a, **k):
        raise compliance.ComplianceAnalysisError("Gemini request failed")

    monkeypatch.setattr(compliance, "analyse_document", _raise)

    response = client.post("/api/compliance/analyse", json=_request())

    assert response.status_code == 502


def test_analyse_rerank_error_maps_to_502(client, monkeypatch):
    def _raise(*a, **k):
        raise compliance.RerankError("reranker request failed")

    monkeypatch.setattr(compliance, "analyse_document", _raise)

    response = client.post("/api/compliance/analyse", json=_request())

    assert response.status_code == 502


def _feedback_request(**overrides):
    base = dict(
        clause_id="H1D4",
        query="footing requirements",
        reported_status="addressed",
        doc="NCC 2025 Volume Two",
        corrected_status="needs_review",
        comment="Document only mentions footings in passing, doesn't give a depth.",
    )
    return {**base, **overrides}


def test_flag_finding_creates_feedback_row(client, feedback_db):
    response = client.post("/api/compliance/feedback", json=_feedback_request())

    assert response.status_code == 201
    body = response.json()
    assert body["clause_id"] == "H1D4"
    assert body["reported_status"] == "addressed"
    assert body["corrected_status"] == "needs_review"
    assert body["id"]
    assert body["created_at"]


def test_flag_finding_rejects_invalid_status(client, feedback_db):
    response = client.post(
        "/api/compliance/feedback", json=_feedback_request(reported_status="wrong")
    )

    assert response.status_code == 422


def test_list_feedback_returns_flagged_findings_most_recent_first(client, feedback_db):
    client.post("/api/compliance/feedback", json=_feedback_request(clause_id="H1D4"))
    client.post("/api/compliance/feedback", json=_feedback_request(clause_id="H1D5"))

    response = client.get("/api/compliance/feedback")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {row["clause_id"] for row in body} == {"H1D4", "H1D5"}


def test_list_feedback_filters_by_clause_id(client, feedback_db):
    client.post("/api/compliance/feedback", json=_feedback_request(clause_id="H1D4"))
    client.post("/api/compliance/feedback", json=_feedback_request(clause_id="H1D5"))

    response = client.get("/api/compliance/feedback", params={"clause_id": "H1D4"})

    body = response.json()
    assert len(body) == 1
    assert body[0]["clause_id"] == "H1D4"
