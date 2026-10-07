"""
Tests for app.services.compliance_analysis.

analyse_document()'s own tests monkeypatch retrieve() and _classify()
directly -- no real embedding/rerank/Gemini calls happen there. _classify()
itself is tested separately below, with a fake Gemini client (same pattern
as test_generation_key_rotation.py), to cover its own prompt-assembly,
response-validation and key-rotation logic rather than treating it as a
black box.
"""

from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from app.core.config import settings
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


def test_analyse_document_dedupes_chunks_sharing_a_clause_id(monkeypatch):
    # A long clause is split across multiple embedded chunks (see
    # app/ingest/chunker.py), so retrieve() can legitimately return the same
    # clause_id twice -- without deduping, that clause gets classified and
    # reported as two identical findings instead of one.
    monkeypatch.setattr(ca, "retrieve", lambda *a, **k: [_chunk(), _chunk()])
    seen_chunks = []

    def _classify(document_text, chunks):
        seen_chunks.extend(chunks)
        return {
            "H1D4": ca._FindingLLM(clause_id="H1D4", status="addressed", explanation="x")
        }

    monkeypatch.setattr(ca, "_classify", _classify)

    report = ca.analyse_document("Some document text.", "footing requirements")

    assert len(seen_chunks) == 1  # the LLM is only asked about it once
    assert len(report.findings) == 1  # and only one finding comes back


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


def test_format_requirement_includes_heading_when_present():
    text = ca._format_requirement(_chunk(heading="Footings"))

    assert "[clause_id: H1D4 -- NCC 2025 Volume Two: Footings]" in text
    assert "Footings must be designed to support the loads." in text


def test_format_requirement_omits_heading_when_absent():
    text = ca._format_requirement(_chunk(heading=None))

    assert "[clause_id: H1D4 -- NCC 2025 Volume Two]" in text
    assert ":" not in text.splitlines()[0].split("--")[1]


def test_format_requirement_falls_back_to_placeholders_for_missing_fields():
    text = ca._format_requirement({})

    assert "unknown clause" in text
    assert "unknown document" in text


def test_format_requirement_lists_every_applicability_qualifier_given():
    chunk = _chunk(
        building_classes=["1a", "1b"],
        jurisdictions=["NSW", "QLD"],
        climate_zones=[1, 2],
        applicability_note="Only for new builds.",
    )

    text = ca._format_requirement(chunk)

    assert "building classes: 1a, 1b" in text
    assert "jurisdictions: NSW, QLD" in text
    assert "climate zones: 1, 2" in text
    assert "Only for new builds." in text
    assert "Applicability:" in text


def test_format_requirement_omits_applicability_line_when_no_qualifiers():
    text = ca._format_requirement(_chunk())

    assert "Applicability:" not in text


def test_build_user_content_includes_every_requirement_and_the_document_text():
    content = ca._build_user_content("Footings: 600mm deep.", [_chunk(), _chunk(clause_id="H1D5")])

    assert "REQUIREMENTS:" in content
    assert "H1D4" in content
    assert "H1D5" in content
    assert "DOCUMENT:\nFootings: 600mm deep." in content


def test_is_quota_error_true_for_429():
    exc = genai_errors.APIError(429, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})

    assert ca._is_quota_error(exc) is True


def test_is_quota_error_true_for_resource_exhausted_status_without_429_code():
    exc = genai_errors.APIError(400, {"error": {"message": "quota", "status": "RESOURCE_EXHAUSTED"}})

    assert ca._is_quota_error(exc) is True


def test_is_quota_error_false_for_an_unrelated_api_error():
    exc = genai_errors.APIError(500, {"error": {"message": "server error", "status": "INTERNAL"}})

    assert ca._is_quota_error(exc) is False


def test_is_quota_error_false_for_a_non_api_error():
    assert ca._is_quota_error(RuntimeError("network blew up")) is False


# --- _classify(): a fake Gemini client, same pattern as
# test_generation_key_rotation.py, rather than monkeypatching _classify
# itself away like analyse_document()'s own tests above do.


def _quota_error() -> genai_errors.APIError:
    return genai_errors.APIError(
        429, {"error": {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}}
    )


def _fake_response(parsed=None, text=None, block_reason=None, candidates="default", finish_reason=None):
    if candidates == "default":
        candidates = [SimpleNamespace(finish_reason=finish_reason)]
    return SimpleNamespace(
        parsed=parsed,
        text=text,
        prompt_feedback=SimpleNamespace(block_reason=block_reason) if block_reason else None,
        candidates=candidates,
    )


class _FakeModels:
    def __init__(self, behaviour):
        self._behaviour = behaviour  # api_key -> response or exception

    def generate_content(self, model, contents, config):
        result = self._behaviour[self._current_key]
        if isinstance(result, Exception):
            raise result
        return result


class _FakeClient:
    def __init__(self, api_key: str, behaviour: dict, http_options=None):
        self.models = _FakeModels(behaviour)
        self.models._current_key = api_key


@pytest.fixture(autouse=True)
def _clear_compliance_client_cache():
    # gemini_keys caches one rotator per process (with per-key cooldowns), so
    # an earlier test exhausting "key1" would otherwise make a later test's
    # first call go to "key2" instead -- tests/services/conftest.py does the
    # same reset, but this file lives outside that directory.
    from app.services import gemini_keys

    ca._clients.clear()
    gemini_keys._rotator = None
    gemini_keys._rotator_keys_cache = None
    yield
    ca._clients.clear()
    gemini_keys._rotator = None
    gemini_keys._rotator_keys_cache = None


def test_classify_raises_clean_error_when_no_key_configured(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")

    with pytest.raises(ca.ComplianceAnalysisError, match="GEMINI_API_KEY is not set"):
        ca._classify("doc text", [_chunk()])


def test_classify_returns_results_keyed_by_clause_id(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key1")
    finding = ca._FindingLLM(clause_id="H1D4", status="addressed", explanation="x")
    behaviour = {"key1": _fake_response(parsed=[finding])}
    monkeypatch.setattr(ca.genai, "Client", lambda api_key, http_options=None: _FakeClient(api_key, behaviour))

    results = ca._classify("doc text", [_chunk()])

    assert results == {"H1D4": finding}


def test_classify_falls_back_to_parsing_text_when_parsed_is_empty(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key1")
    text = '[{"clause_id": "H1D4", "status": "addressed", "explanation": "x"}]'
    behaviour = {"key1": _fake_response(parsed=None, text=text)}
    monkeypatch.setattr(ca.genai, "Client", lambda api_key, http_options=None: _FakeClient(api_key, behaviour))

    results = ca._classify("doc text", [_chunk()])

    assert results["H1D4"].status == "addressed"


def test_classify_raises_when_fallback_text_is_not_valid_json(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key1")
    behaviour = {"key1": _fake_response(parsed=None, text="not json")}
    monkeypatch.setattr(ca.genai, "Client", lambda api_key, http_options=None: _FakeClient(api_key, behaviour))

    with pytest.raises(ca.ComplianceAnalysisError, match="Could not parse"):
        ca._classify("doc text", [_chunk()])


def test_classify_raises_when_prompt_is_blocked(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key1")
    behaviour = {"key1": _fake_response(block_reason="SAFETY")}
    monkeypatch.setattr(ca.genai, "Client", lambda api_key, http_options=None: _FakeClient(api_key, behaviour))

    with pytest.raises(ca.ComplianceAnalysisError, match="Gemini blocked the prompt"):
        ca._classify("doc text", [_chunk()])


def test_classify_raises_when_no_candidates_returned(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key1")
    behaviour = {"key1": _fake_response(candidates=[])}
    monkeypatch.setattr(ca.genai, "Client", lambda api_key, http_options=None: _FakeClient(api_key, behaviour))

    with pytest.raises(ca.ComplianceAnalysisError, match="no candidates"):
        ca._classify("doc text", [_chunk()])


def test_classify_raises_when_generation_cut_off(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key1")
    behaviour = {"key1": _fake_response(finish_reason="MAX_TOKENS")}
    monkeypatch.setattr(ca.genai, "Client", lambda api_key, http_options=None: _FakeClient(api_key, behaviour))

    with pytest.raises(ca.ComplianceAnalysisError, match="did not complete cleanly"):
        ca._classify("doc text", [_chunk()])


def test_classify_rotates_to_next_key_after_quota_error(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key1,key2")
    finding = ca._FindingLLM(clause_id="H1D4", status="addressed", explanation="x")
    behaviour = {"key1": _quota_error(), "key2": _fake_response(parsed=[finding])}
    monkeypatch.setattr(ca.genai, "Client", lambda api_key, http_options=None: _FakeClient(api_key, behaviour))

    results = ca._classify("doc text", [_chunk()])

    assert results == {"H1D4": finding}


def test_classify_raises_quota_exceeded_once_every_key_is_out(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key1,key2")
    behaviour = {"key1": _quota_error(), "key2": _quota_error()}
    monkeypatch.setattr(ca.genai, "Client", lambda api_key, http_options=None: _FakeClient(api_key, behaviour))

    with pytest.raises(ca.QuotaExceededError):
        ca._classify("doc text", [_chunk()])


def test_classify_raises_without_retrying_a_non_quota_api_error(monkeypatch):
    # Distinct from the generic-Exception case below: a genai APIError that
    # isn't a quota error (e.g. a 500) hits its own non-retrying branch,
    # separate from the plain `except Exception` catch-all.
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key1,key2")
    server_error = genai_errors.APIError(500, {"error": {"message": "boom", "status": "INTERNAL"}})
    behaviour = {"key1": server_error}
    monkeypatch.setattr(ca.genai, "Client", lambda api_key, http_options=None: _FakeClient(api_key, behaviour))

    with pytest.raises(ca.ComplianceAnalysisError, match="Gemini request failed"):
        ca._classify("doc text", [_chunk()])


def test_classify_raises_without_retrying_a_non_quota_error(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEYS", "key1,key2")
    calls = []

    class _ExplodingModels:
        def generate_content(self, model, contents, config):
            calls.append("called")
            raise RuntimeError("network blew up")

    class _ExplodingClient:
        def __init__(self, api_key, http_options=None):
            self.models = _ExplodingModels()

    monkeypatch.setattr(ca.genai, "Client", _ExplodingClient)

    with pytest.raises(ca.ComplianceAnalysisError):
        ca._classify("doc text", [_chunk()])

    assert len(calls) == 1  # never tried key2
