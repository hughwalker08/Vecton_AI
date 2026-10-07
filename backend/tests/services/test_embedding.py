"""
Tests for app.services.embedding.embed_text() -- a fake Gemini client (same
pattern as test_generation_key_rotation.py), so no real embedding calls
happen. Key rotation resets between tests via tests/services/conftest.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from app.services import embedding


def _quota_error() -> genai_errors.APIError:
    return genai_errors.APIError(
        429, {"error": {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}}
    )


def _response(values=(0.1, 0.2, 0.3)):
    return SimpleNamespace(embeddings=[SimpleNamespace(values=list(values))])


class _FakeModels:
    def __init__(self, behaviour, calls):
        self._behaviour = behaviour  # api_key -> response or exception
        self._calls = calls
        self._current_key = None

    def embed_content(self, model, contents, config):
        self._calls.append({"key": self._current_key, "contents": contents, "config": config})
        result = self._behaviour[self._current_key]
        if isinstance(result, Exception):
            raise result
        return result


def _install_fake_client(monkeypatch, behaviour):
    calls = []

    def _factory(api_key, http_options=None):
        models = _FakeModels(behaviour, calls)
        models._current_key = api_key
        return SimpleNamespace(models=models)

    monkeypatch.setattr(embedding.genai, "Client", _factory)
    return calls


@pytest.fixture(autouse=True)
def _clear_client_cache():
    embedding._clients.clear()
    yield
    embedding._clients.clear()


def test_embed_text_returns_the_embedding_values_as_a_list(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    _install_fake_client(monkeypatch, {"key1": _response([0.5, -0.25])})

    assert embedding.embed_text("footings") == [0.5, -0.25]


def test_embed_text_passes_the_text_task_type_and_dimension_through(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    calls = _install_fake_client(monkeypatch, {"key1": _response()})

    embedding.embed_text("footings", task_type="RETRIEVAL_DOCUMENT")

    assert calls[0]["contents"] == "footings"
    assert calls[0]["config"].task_type == "RETRIEVAL_DOCUMENT"
    assert calls[0]["config"].output_dimensionality == backend_settings.EMBEDDING_DIM


def test_embed_text_defaults_to_the_retrieval_query_task_type(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    calls = _install_fake_client(monkeypatch, {"key1": _response()})

    embedding.embed_text("footings")

    assert calls[0]["config"].task_type == "RETRIEVAL_QUERY"


def test_embed_text_raises_clean_error_when_no_key_configured(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "")
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEY", "")

    with pytest.raises(embedding.EmbeddingError, match="GEMINI_API_KEY is not set"):
        embedding.embed_text("footings")


def test_embed_text_raises_when_gemini_returns_no_embedding(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1")
    _install_fake_client(monkeypatch, {"key1": SimpleNamespace(embeddings=[])})

    with pytest.raises(embedding.EmbeddingError, match="no embedding"):
        embedding.embed_text("footings")


def test_embed_text_rotates_to_next_key_after_quota_error(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    calls = _install_fake_client(monkeypatch, {"key1": _quota_error(), "key2": _response([0.9])})

    assert embedding.embed_text("footings") == [0.9]
    assert [c["key"] for c in calls] == ["key1", "key2"]


def test_embed_text_raises_quota_exceeded_once_every_key_is_out(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    _install_fake_client(monkeypatch, {"key1": _quota_error(), "key2": _quota_error()})

    with pytest.raises(embedding.QuotaExceededError):
        embedding.embed_text("footings")


def test_embed_text_does_not_retry_a_non_quota_api_error(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    server_error = genai_errors.APIError(500, {"error": {"message": "boom", "status": "INTERNAL"}})
    calls = _install_fake_client(monkeypatch, {"key1": server_error})

    with pytest.raises(embedding.EmbeddingError, match="embedding request failed"):
        embedding.embed_text("footings")

    assert len(calls) == 1  # never tried key2


def test_embed_text_does_not_retry_a_generic_exception(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    calls = _install_fake_client(monkeypatch, {"key1": RuntimeError("network blew up")})

    with pytest.raises(embedding.EmbeddingError, match="embedding request failed"):
        embedding.embed_text("footings")

    assert len(calls) == 1


def test_is_quota_error_true_for_429_and_resource_exhausted_only():
    assert embedding._is_quota_error(_quota_error()) is True
    assert embedding._is_quota_error(
        genai_errors.APIError(400, {"error": {"message": "q", "status": "RESOURCE_EXHAUSTED"}})
    ) is True
    assert embedding._is_quota_error(
        genai_errors.APIError(500, {"error": {"message": "x", "status": "INTERNAL"}})
    ) is False
    assert embedding._is_quota_error(RuntimeError("nope")) is False
