"""
Shared Gemini API key rotation.

Several teammates' personal Gemini API keys are pooled (settings.GEMINI_API_KEYS,
see backend/.env.example) so the app keeps serving requests after any single
key's rate limit or daily quota is hit, rather than failing until someone
swaps the key by hand. generation.py, embedding.py, compliance_analysis.py and
image_description.py all go through get_rotator() / call_with_rotation() here,
sharing ONE rotator so a key marked exhausted by one of them is skipped by the
others too.

Keys never live in code or in git -- only in the environment / backend/.env
(gitignored) locally, and as a Render dashboard env var (sync: false in
render.yaml) in production.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Callable, TypeVar

from app.core.config import settings

T = TypeVar("T")

# How long to skip a key after it reports quota exhaustion, when the 429
# response itself doesn't say how long to wait. Short enough that a key
# whose daily quota resets mid-session gets picked back up without a
# restart; long enough not to waste a request re-trying a key that's still
# out every single call.
DEFAULT_COOLDOWN_SECONDS = 300.0
# 429s report their own retryDelay, but a daily-quota one can ask for hours.
# Cap how long we honour that so one key doesn't sit out far longer than it
# takes the others to cycle back around.
MAX_COOLDOWN_SECONDS = 900.0


def _retry_delay_seconds(exc: Exception) -> float | None:
    """Pull a retry delay out of a 429's error body, if one is given."""
    blob = str(exc)
    match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)", blob)
    if match:
        return float(match.group(1))
    match = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", blob)
    if match:
        return float(match.group(1))
    match = re.search(r"retry in\s+([\d.]+)", blob, re.I)
    if match:
        return float(match.group(1))
    return None


def quota_wait_hint(exc: Exception) -> str:
    """Human-readable suffix for an error message, e.g. ' Try again in about 20s.'"""
    seconds = _retry_delay_seconds(exc)
    return f" Try again in about {seconds:.0f}s." if seconds else ""


class KeyRotator:
    """Round-robins through a fixed list of keys, skipping ones on cooldown."""

    def __init__(self, keys: list[str]):
        if not keys:
            raise ValueError("KeyRotator needs at least one key")
        self._keys = keys
        self._i = 0
        self._cooldown_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._keys)

    def current(self) -> str:
        """The key to try next: the pointer's key if it isn't cooling down,
        otherwise the next non-cooling-down key, otherwise whichever key
        frees up soonest."""
        with self._lock:
            now = time.monotonic()
            for offset in range(len(self._keys)):
                i = (self._i + offset) % len(self._keys)
                key = self._keys[i]
                if now >= self._cooldown_until.get(key, 0.0):
                    self._i = i
                    return key
            soonest = min(self._keys, key=lambda k: self._cooldown_until.get(k, 0.0))
            self._i = self._keys.index(soonest)
            return soonest

    def label_for(self, key: str) -> str:
        idx = self._keys.index(key) + 1
        return f"key {idx}/{len(self._keys)} (...{key[-4:]})"

    def mark_exhausted(self, key: str, retry_after: float | None = None) -> None:
        """Put `key` on cooldown and advance the pointer past it."""
        cooldown = min(retry_after, MAX_COOLDOWN_SECONDS) if retry_after else DEFAULT_COOLDOWN_SECONDS
        with self._lock:
            self._cooldown_until[key] = time.monotonic() + cooldown
            self._i = (self._keys.index(key) + 1) % len(self._keys)


_rotator: KeyRotator | None = None
_rotator_keys_cache: tuple[str, ...] | None = None
_rotator_lock = threading.Lock()


def get_rotator() -> KeyRotator | None:
    """The shared rotator, (re)built if settings.gemini_api_keys has changed
    since it was last built (e.g. a test monkeypatching the key). None if no
    key is configured at all."""
    global _rotator, _rotator_keys_cache
    keys = tuple(settings.gemini_api_keys)
    with _rotator_lock:
        if not keys:
            _rotator, _rotator_keys_cache = None, None
        elif keys != _rotator_keys_cache:
            _rotator, _rotator_keys_cache = KeyRotator(list(keys)), keys
        return _rotator


def call_with_rotation(is_quota_error: Callable[[Exception], bool], make_call: Callable[[str], T]) -> T:
    """Call `make_call(api_key)`, rotating to the next key on a quota error.

    `is_quota_error` classifies an exception raised by `make_call` as a
    rate-limit/quota failure (as opposed to some other error, which is never
    retried with a different key -- it propagates immediately). Tries at
    most once per configured key; once every key has failed with a quota
    error, re-raises the last one so the caller can turn it into its own
    QuotaExceededError.
    """
    rotator = get_rotator()
    if rotator is None:
        return make_call(settings.GEMINI_API_KEY)

    last_exc: Exception | None = None
    for _ in range(len(rotator)):
        key = rotator.current()
        try:
            return make_call(key)
        except Exception as exc:
            if not is_quota_error(exc):
                raise
            rotator.mark_exhausted(key, _retry_delay_seconds(exc))
            last_exc = exc
    assert last_exc is not None
    raise last_exc
