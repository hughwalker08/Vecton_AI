"""
Embedding service: Gemini `gemini-embedding-2`, 768-dim output
(settings.EMBEDDING_MODEL_NAME / settings.EMBEDDING_DIM).

This must stay in lockstep with whatever produced
app/ingest/output/*.embedded.json (see scripts/embed_chunks.py and the
matching .meta.json) -- query and corpus vectors only compare meaningfully
if they came from the same model, task type and dimensionality.

  - task_type="RETRIEVAL_QUERY" for a user question (this module's use case).
  - task_type="RETRIEVAL_DOCUMENT" was used when embedding corpus chunks
    (see scripts/embed_chunks.py, the offline batch job that produced the
    .embedded.json files).
"""

from __future__ import annotations

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import settings
from app.services.gemini_keys import call_with_rotation, quota_wait_hint

_clients: dict[str, genai.Client] = {}


class EmbeddingError(Exception):
    """Raised when embedding cannot run (missing config, API failure, etc.)."""


class QuotaExceededError(EmbeddingError):
    """Raised when Gemini's rate limit or daily quota has been used up."""


def _is_quota_error(exc: Exception) -> bool:
    return isinstance(exc, genai_errors.APIError) and (
        exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED"
    )


def _client_for(key: str) -> genai.Client:
    if key not in _clients:
        _clients[key] = genai.Client(api_key=key)
    return _clients[key]


def embed_text(text: str, task_type: str = "RETRIEVAL_QUERY") -> list[float]:
    """Return an `EMBEDDING_DIM`-dim embedding vector for `text`."""
    if not settings.gemini_api_keys:
        raise EmbeddingError(
            "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and fill it in (or export GEMINI_API_KEY / GEMINI_API_KEYS)."
        )

    def _call(key: str):
        client = _client_for(key)
        try:
            return client.models.embed_content(
                model=settings.EMBEDDING_MODEL_NAME,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=settings.EMBEDDING_DIM,
                ),
            )
        except genai_errors.APIError as exc:
            if _is_quota_error(exc):
                raise
            raise EmbeddingError(f"Gemini embedding request failed: {exc}") from exc
        except Exception as exc:
            raise EmbeddingError(f"Gemini embedding request failed: {exc}") from exc

    try:
        response = call_with_rotation(_is_quota_error, _call)
    except genai_errors.APIError as exc:
        raise QuotaExceededError(
            "Gemini's usage limit has been reached for now." + quota_wait_hint(exc)
        ) from exc

    if not response.embeddings:
        raise EmbeddingError("Gemini returned no embedding.")
    return list(response.embeddings[0].values)
