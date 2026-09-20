"""
Fixtures shared by tests/services/*.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import gemini_keys


@pytest.fixture()
def backend_settings():
    """The real app.core.config.settings singleton, for monkeypatching
    GEMINI_API_KEY(S) in a single test without touching a real .env."""
    return settings


@pytest.fixture(autouse=True)
def _reset_key_rotator():
    """gemini_keys caches one rotator per process, keyed by the configured
    key tuple -- reset it around every test so cooldown state (or the
    rotator's position) from one test can't leak into the next one that
    happens to configure the same key values."""
    gemini_keys._rotator = None
    gemini_keys._rotator_keys_cache = None
    yield
    gemini_keys._rotator = None
    gemini_keys._rotator_keys_cache = None
