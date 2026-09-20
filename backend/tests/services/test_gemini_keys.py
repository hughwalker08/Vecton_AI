"""
Tests for app.services.gemini_keys: the shared Gemini API key rotator used by
generation.py, embedding.py, compliance_analysis.py and image_description.py.
"""

from __future__ import annotations

import time

import pytest

from app.services import gemini_keys as gk
from app.services.gemini_keys import KeyRotator, call_with_rotation, quota_wait_hint


class _QuotaError(Exception):
    pass


class _OtherError(Exception):
    pass


def _is_quota(exc: Exception) -> bool:
    return isinstance(exc, _QuotaError)


def test_rotator_requires_at_least_one_key():
    with pytest.raises(ValueError):
        KeyRotator([])


def test_rotator_starts_at_first_key():
    rotator = KeyRotator(["a", "b", "c"])

    assert rotator.current() == "a"


def test_rotator_advances_past_an_exhausted_key():
    rotator = KeyRotator(["a", "b", "c"])

    rotator.mark_exhausted("a")

    assert rotator.current() == "b"


def test_rotator_skips_multiple_exhausted_keys():
    rotator = KeyRotator(["a", "b", "c"])

    rotator.mark_exhausted("a")
    rotator.mark_exhausted("b")

    assert rotator.current() == "c"


def test_rotator_falls_back_to_soonest_key_when_all_exhausted():
    rotator = KeyRotator(["a", "b"])

    rotator.mark_exhausted("a", retry_after=100)
    rotator.mark_exhausted("b", retry_after=1)

    # Both are cooling down -- "b" clears first, so it's handed out again.
    assert rotator.current() == "b"


def test_rotator_caps_cooldown_at_max_seconds(monkeypatch):
    rotator = KeyRotator(["a", "b"])
    fake_now = 1_000.0
    monkeypatch.setattr(time, "monotonic", lambda: fake_now)

    rotator.mark_exhausted("a", retry_after=10_000)  # way over MAX_COOLDOWN_SECONDS

    assert rotator._cooldown_until["a"] == fake_now + gk.MAX_COOLDOWN_SECONDS


def test_rotator_label_for_shows_position_and_last_four_chars():
    rotator = KeyRotator(["AIzaSyABCD1234", "AIzaSyEFGH5678"])

    assert rotator.label_for("AIzaSyABCD1234") == "key 1/2 (...1234)"
    assert rotator.label_for("AIzaSyEFGH5678") == "key 2/2 (...5678)"


def test_call_with_rotation_returns_result_on_first_key(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")

    result = call_with_rotation(_is_quota, lambda key: f"ok:{key}")

    assert result == "ok:key1"


def test_call_with_rotation_moves_to_next_key_on_quota_error(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    seen: list[str] = []

    def _call(key: str) -> str:
        seen.append(key)
        if key == "key1":
            raise _QuotaError("429")
        return f"ok:{key}"

    result = call_with_rotation(_is_quota, _call)

    assert result == "ok:key2"
    assert seen == ["key1", "key2"]


def test_call_with_rotation_raises_last_error_when_every_key_exhausted(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")

    def _call(key: str) -> str:
        raise _QuotaError(f"429 from {key}")

    with pytest.raises(_QuotaError, match="key2"):
        call_with_rotation(_is_quota, _call)


def test_call_with_rotation_does_not_retry_non_quota_errors(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    seen: list[str] = []

    def _call(key: str) -> str:
        seen.append(key)
        raise _OtherError("boom")

    with pytest.raises(_OtherError):
        call_with_rotation(_is_quota, _call)

    assert seen == ["key1"]  # never tried key2


def test_call_with_rotation_uses_single_key_directly_when_no_keys_configured(
    monkeypatch, backend_settings
):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "")
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEY", "solo")

    result = call_with_rotation(_is_quota, lambda key: f"ok:{key}")

    assert result == "ok:solo"


def test_get_rotator_rebuilds_when_configured_keys_change(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key1,key2")
    first = gk.get_rotator()

    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "key3,key4")
    second = gk.get_rotator()

    assert first is not second
    assert second.current() == "key3"


def test_get_rotator_returns_none_when_no_keys_configured(monkeypatch, backend_settings):
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEYS", "")
    monkeypatch.setattr(backend_settings, "GEMINI_API_KEY", "")

    assert gk.get_rotator() is None


def test_quota_wait_hint_reads_retry_delay_from_error_body():
    exc = Exception('{"retryDelay": "23s"}')

    assert quota_wait_hint(exc) == " Try again in about 23s."


def test_quota_wait_hint_empty_when_no_delay_present():
    assert quota_wait_hint(Exception("plain failure")) == ""
