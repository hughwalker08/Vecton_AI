"""
Tests for app.services.compliance_analysis.

retrieve() and the Gemini-calling _classify() are monkeypatched directly on
the module -- no real embedding/rerank/Gemini calls happen in this file.
"""

import pytest

from app.services import compliance_analysis as ca


def _chunk(**overrides):
    base = {
        "clause_id": "H1D4",
        "doc": "NCC 2025 Volume Two",
        "heading": "Footings",
        "text": "Footings must be designed to support the loads.",
        "source_url": "https://ncc.abcb.gov.au/H1D4",
    }
    return {**base, **overrides}


def test_analyse_document_rejects_empty_document_text():
    with pytest.raises(ValueError):
        ca.analyse_document("   ", "footing requirements")


def test_analyse_document_rejects_empty_query():
    with pytest.raises(ValueError):
        ca.analyse_document("Some document text.", "   ")


def test_analyse_document_returns_empty_report_when_nothing_retrieved(monkeypatch):
    monkeypatch.setattr(ca, "retrieve", lambda *a, **k: [])
    called = []
    monkeypatch.setattr(ca, "_classify", lambda *a, **k: called.append(1))

    report = ca.analyse_document("Some document text.", "footing requirements")

    assert report.findings == []
    assert called == []  # classification is never even attempted


def test_analyse_document_builds_findings_from_classification(monkeypatch):
    monkeypatch.setattr(ca, "retrieve", lambda *a, **k: [_chunk()])
    monkeypatch.setattr(
        ca,
        "_classify",
        lambda *a, **k: {
            "H1D4": ca._FindingLLM(
                clause_id="H1D4",
                status="addressed",
                explanation="Footing depth is specified and meets the requirement.",
                evidence="Footings: 600mm deep.",
            )
        },
    )

    report = ca.analyse_document("Footings: 600mm deep.", "footing requirements")

    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.clause_id == "H1D4"
    assert finding.status == "addressed"
    assert finding.evidence == "Footings: 600mm deep."
    assert finding.source_url == "https://ncc.abcb.gov.au/H1D4"


def test_analyse_document_falls_back_to_needs_review_for_unclassified_clause(monkeypatch):
    monkeypatch.setattr(ca, "retrieve", lambda *a, **k: [_chunk()])
    monkeypatch.setattr(ca, "_classify", lambda *a, **k: {})  # model didn't return this clause

    report = ca.analyse_document("Some document text.", "footing requirements")

    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.clause_id == "H1D4"
    assert finding.status == "needs_review"
    assert "did not return a classification" in finding.explanation


def test_compliance_report_counts_every_status_even_at_zero():
    report = ca.ComplianceReport(
        query="q",
        findings=[
            ca.ComplianceFinding(clause_id="A", doc="d", status="addressed", explanation="x"),
            ca.ComplianceFinding(clause_id="B", doc="d", status="addressed", explanation="x"),
            ca.ComplianceFinding(clause_id="C", doc="d", status="missing", explanation="x"),
        ],
    )

    assert report.counts == {
        "addressed": 2,
        "missing": 1,
        "contradicted": 0,
        "needs_review": 0,
    }
