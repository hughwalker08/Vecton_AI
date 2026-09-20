"""
Tests that generation.generate_answer() rotates through GEMINI_API_KEYS on a
429 instead of failing on the first exhausted key -- see app/services/
gemini_keys.py for the shared rotation logic this wires into.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import errors as genai_errors

from app.services import generation


def _quota_error() -> genai_errors.APIError:
    return genai_errors.APIError(
        429, {"error": {"message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}}
    )


def _fake_response(text: str = "an answer") -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        prompt_feedback=None,
        candidates=[SimpleNamespace(finish_reason=None)],
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
def _clear_client_cache():
    generation._clients.clear()
    yield
    generation._clients.clear()


def test_generate_answer_rotates_to_next_key_after_quota_error(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    behaviour = {"key1": _quota_error(), "key2": _fake_response("answer from key2")}
    monkeypatch.setattr(
        generation.genai, "Client", lambda api_key, http_options=None: _FakeClient(api_key, behaviour)
    )

    answer = generation.generate_answer("what is the riser height?", [])

    assert answer == "answer from key2"


def test_generate_answer_raises_quota_exceeded_once_every_key_is_out(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    behaviour = {"key1": _quota_error(), "key2": _quota_error()}
    monkeypatch.setattr(
        generation.genai, "Client", lambda api_key, http_options=None: _FakeClient(api_key, behaviour)
    )

    with pytest.raises(generation.QuotaExceededError):
        generation.generate_answer("what is the riser height?", [])


def test_generate_answer_raises_without_retrying_a_non_quota_error(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    calls: list[str] = []

    class _ExplodingModels:
        def generate_content(self, model, contents, config):
            calls.append("called")
            raise RuntimeError("network blew up")

    class _ExplodingClient:
        def __init__(self, api_key, http_options=None):
            self.models = _ExplodingModels()

    monkeypatch.setattr(generation.genai, "Client", _ExplodingClient)

    with pytest.raises(generation.GenerationError):
        generation.generate_answer("what is the riser height?", [])

    assert len(calls) == 1  # never tried key2


def test_generate_answer_raises_clean_error_when_no_key_configured(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "")
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEY", "")

    with pytest.raises(generation.GenerationError, match="GEMINI_API_KEY is not set"):
        generation.generate_answer("what is the riser height?", [])
