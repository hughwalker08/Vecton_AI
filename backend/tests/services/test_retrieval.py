"""
Tests for app.services.retrieval.

hybrid_search() hits a real Postgres connection and embed_text() -- both
monkeypatched here rather than used for real (no DB, no Gemini calls).
rerank() hits Hugging Face's Inference router via retrieval._http -- also
monkeypatched. retrieve() is just hybrid_search() + rerank() glued
together, so its own test monkeypatches both of those instead of going
two layers deep.
"""

from __future__ import annotations

import httpx
import pytest

from app.services import retrieval


def _candidate(**overrides):
    base = {"clause_id": "H1D4", "doc": "NCC 2025 Volume Two", "text": "Footings must comply."}
    return {**base, **overrides}


def _response(status_code, json_body=None, headers=None):
    # httpx.Response.raise_for_status() needs a request attached, or it
    # refuses to run at all -- irrelevant to what's being tested here, but
    # has to be present for a response built by hand like this.
    request = httpx.Request("POST", "https://router.huggingface.co/fake")
    return httpx.Response(status_code, request=request, json=json_body, headers=headers or {})


def test_to_vector_literal_formats_as_pgvector_text():
    assert retrieval._to_vector_literal([0.1, 0.2, -0.3]) == "[0.1,0.2,-0.3]"


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows, captured):
        self._rows = rows
        self._captured = captured

    def execute(self, _stmt, params):
        self._captured.update(params)
        return _FakeResult(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _FakeEngine:
    def __init__(self, rows=(), captured=None):
        self._rows = list(rows)
        self.captured = captured if captured is not None else {}

    def connect(self):
        return _FakeConn(self._rows, self.captured)


def test_hybrid_search_rejects_an_unsupported_jurisdiction():
    with pytest.raises(ValueError, match="Unsupported jurisdiction"):
        retrieval.hybrid_search("footings", jurisdiction="XX")


def test_hybrid_search_normalises_jurisdiction_case(monkeypatch):
    monkeypatch.setattr(retrieval, "embed_text", lambda *a, **k: [0.1, 0.2])
    fake_engine = _FakeEngine()
    monkeypatch.setattr(retrieval, "engine", fake_engine)

    retrieval.hybrid_search("footings", jurisdiction="nsw")

    assert fake_engine.captured["jurisdiction"] == "NSW"


def test_hybrid_search_passes_none_jurisdiction_through_unfiltered(monkeypatch):
    monkeypatch.setattr(retrieval, "embed_text", lambda *a, **k: [0.1, 0.2])
    fake_engine = _FakeEngine()
    monkeypatch.setattr(retrieval, "engine", fake_engine)

    retrieval.hybrid_search("footings")

    assert fake_engine.captured["jurisdiction"] is None


def test_hybrid_search_binds_top_k_and_the_embedded_query_vector(monkeypatch):
    monkeypatch.setattr(retrieval, "embed_text", lambda *a, **k: [0.5, -0.25])
    fake_engine = _FakeEngine()
    monkeypatch.setattr(retrieval, "engine", fake_engine)

    retrieval.hybrid_search("footings", top_k=3)

    assert fake_engine.captured["top_k"] == 3
    assert fake_engine.captured["qvec"] == "[0.5,-0.25]"
    assert fake_engine.captured["q"] == "footings"


def test_hybrid_search_returns_rows_as_plain_dicts(monkeypatch):
    monkeypatch.setattr(retrieval, "embed_text", lambda *a, **k: [0.1, 0.2])
    row = {"clause_id": "H1D4", "doc": "NCC 2025 Volume Two", "fused_score": 0.5}
    monkeypatch.setattr(retrieval, "engine", _FakeEngine(rows=[row]))

    results = retrieval.hybrid_search("footings")

    assert results == [row]


def test_rerank_returns_empty_list_without_calling_hf_for_no_candidates(monkeypatch):
    called = []
    monkeypatch.setattr(retrieval._http, "post", lambda *a, **k: called.append(1))

    assert retrieval.rerank("q", []) == []
    assert called == []


@pytest.fixture(autouse=True)
def _default_to_hf_backend(monkeypatch, backend_settings):
    """backend/.env may set RERANKER_BACKEND=local; keep these tests hermetic."""
    monkeypatch.setattr(backend_settings, "RERANKER_BACKEND", "hf")


def test_rerank_raises_when_hf_token_not_configured(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "HF_API_TOKEN", "")

    with pytest.raises(retrieval.RerankError, match="HF_API_TOKEN"):
        retrieval.rerank("q", [_candidate()])


def test_rerank_scores_and_sorts_candidates_descending(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "HF_API_TOKEN", "fake-token")
    monkeypatch.setattr(
        retrieval._http, "post",
        lambda *a, **k: _response(200, json_body=[[{"score": 0.2}, {"score": 0.9}]]),
    )
    candidates = [_candidate(clause_id="A"), _candidate(clause_id="B")]

    results = retrieval.rerank("q", candidates, top_n=10)

    assert [r["clause_id"] for r in results] == ["B", "A"]
    assert results[0]["rerank_score"] == 0.9


def test_rerank_truncates_to_top_n(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "HF_API_TOKEN", "fake-token")
    scores = [0.1, 0.5, 0.9]
    monkeypatch.setattr(
        retrieval._http, "post",
        lambda *a, **k: _response(200, json_body=[[{"score": s} for s in scores]]),
    )
    candidates = [_candidate(clause_id=str(i)) for i in range(3)]

    results = retrieval.rerank("q", candidates, top_n=1)

    assert len(results) == 1
    assert results[0]["rerank_score"] == 0.9


def test_rerank_raises_quota_exceeded_on_429_with_retry_after(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "HF_API_TOKEN", "fake-token")
    monkeypatch.setattr(
        retrieval._http, "post",
        lambda *a, **k: _response(429, json_body={}, headers={"retry-after": "20"}),
    )

    with pytest.raises(retrieval.QuotaExceededError, match="20s"):
        retrieval.rerank("q", [_candidate()])


def test_rerank_raises_quota_exceeded_on_429_without_retry_after(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "HF_API_TOKEN", "fake-token")
    monkeypatch.setattr(retrieval._http, "post", lambda *a, **k: _response(429, json_body={}))

    with pytest.raises(retrieval.QuotaExceededError):
        retrieval.rerank("q", [_candidate()])


def test_rerank_raises_rerank_error_on_other_http_status(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "HF_API_TOKEN", "fake-token")
    monkeypatch.setattr(retrieval._http, "post", lambda *a, **k: _response(500, json_body={}))

    with pytest.raises(retrieval.RerankError):
        retrieval.rerank("q", [_candidate()])


def test_rerank_raises_rerank_error_on_network_failure(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "HF_API_TOKEN", "fake-token")

    def _raise(*a, **k):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(retrieval._http, "post", _raise)

    with pytest.raises(retrieval.RerankError):
        retrieval.rerank("q", [_candidate()])


def test_rerank_raises_on_malformed_response_shape(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "HF_API_TOKEN", "fake-token")
    monkeypatch.setattr(retrieval._http, "post", lambda *a, **k: _response(200, json_body={"unexpected": True}))

    with pytest.raises(retrieval.RerankError, match="Unexpected rerank response shape"):
        retrieval.rerank("q", [_candidate()])


def test_rerank_raises_when_score_count_does_not_match_candidate_count(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "HF_API_TOKEN", "fake-token")
    monkeypatch.setattr(retrieval._http, "post", lambda *a, **k: _response(200, json_body=[[{"score": 0.5}]]))

    with pytest.raises(retrieval.RerankError, match="2 candidates"):
        retrieval.rerank("q", [_candidate(), _candidate()])


def test_retrieve_runs_hybrid_search_then_rerank_in_order(monkeypatch):
    calls = []
    monkeypatch.setattr(
        retrieval, "hybrid_search",
        lambda query, top_k, jurisdiction: calls.append(("hybrid_search", query, top_k, jurisdiction))
        or [_candidate()],
    )
    monkeypatch.setattr(
        retrieval, "rerank",
        lambda query, candidates, top_n: calls.append(("rerank", query, candidates, top_n))
        or [{"reranked": True}],
    )

    result = retrieval.retrieve("footings", top_k=5, candidate_pool=20, jurisdiction="NSW")

    assert result == [{"reranked": True}]
    assert calls[0] == ("hybrid_search", "footings", 20, "NSW")
    assert calls[1][0] == "rerank" and calls[1][3] == 5


# --- RERANKER_BACKEND=local --------------------------------------------


def test_rerank_defaults_to_the_hosted_backend(monkeypatch, backend_settings):
    # The deployed backend must keep calling Hugging Face unless someone opts
    # in to the local model -- PyTorch isn't in requirements.txt.
    assert backend_settings.RERANKER_BACKEND == "hf"
    monkeypatch.setattr(backend_settings, "HF_API_TOKEN", "fake-token")
    monkeypatch.setattr(retrieval, "_local_scores", lambda *a, **k: pytest.fail("must not run locally"))
    monkeypatch.setattr(retrieval._http, "post", lambda *a, **k: _response(200, json_body=[[{"score": 0.4}]]))

    assert retrieval.rerank("q", [_candidate()])[0]["rerank_score"] == 0.4


def test_rerank_local_backend_never_calls_hugging_face_or_needs_a_token(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "RERANKER_BACKEND", "local")
    monkeypatch.setattr(backend_settings, "HF_API_TOKEN", "")
    monkeypatch.setattr(retrieval._http, "post", lambda *a, **k: pytest.fail("must not call the hosted API"))
    monkeypatch.setattr(retrieval, "_local_scores", lambda query, candidates: [0.2, 0.9])

    results = retrieval.rerank("q", [_candidate(clause_id="A"), _candidate(clause_id="B")])

    assert [r["clause_id"] for r in results] == ["B", "A"]
    assert results[0]["rerank_score"] == 0.9


def test_rerank_local_backend_still_rejects_a_score_count_mismatch(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "RERANKER_BACKEND", "local")
    monkeypatch.setattr(retrieval, "_local_scores", lambda query, candidates: [0.5])

    with pytest.raises(retrieval.RerankError, match="2 candidates"):
        retrieval.rerank("q", [_candidate(), _candidate()])


class _FakeCrossEncoder:
    loads = 0

    def __init__(self, name, max_length):
        type(self).loads += 1
        self.name, self.max_length = name, max_length
        self.seen = None

    def predict(self, pairs):
        self.seen = pairs
        return [0.25, 0.75]  # plain floats, as numpy would hand back


def _install_fake_sentence_transformers(monkeypatch):
    import sys
    from types import SimpleNamespace

    _FakeCrossEncoder.loads = 0
    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(CrossEncoder=_FakeCrossEncoder))
    monkeypatch.setattr(retrieval, "_local_model", None)


def test_local_scores_pairs_the_query_with_each_candidate_text(monkeypatch, backend_settings):
    _install_fake_sentence_transformers(monkeypatch)

    scores = retrieval._local_scores("q", [_candidate(text="first"), _candidate(text=None)])

    assert scores == [0.25, 0.75]
    assert retrieval._local_model.seen == [("q", "first"), ("q", "")]
    assert retrieval._local_model.name == backend_settings.RERANKER_MODEL_NAME
    assert retrieval._local_model.max_length == retrieval.RERANKER_MAX_LENGTH


def test_local_scores_loads_the_model_once_and_reuses_it(monkeypatch):
    # ~1 GB model: reloading per question would add seconds to every chat.
    _install_fake_sentence_transformers(monkeypatch)

    retrieval._local_scores("q", [_candidate(), _candidate()])
    retrieval._local_scores("q2", [_candidate(), _candidate()])

    assert _FakeCrossEncoder.loads == 1


def test_local_scores_explains_how_to_install_the_extra_packages(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # makes the import fail

    with pytest.raises(retrieval.RerankError, match="requirements-local-rerank.txt"):
        retrieval._local_scores("q", [_candidate()])
