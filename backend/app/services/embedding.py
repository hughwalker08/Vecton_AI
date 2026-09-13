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

import re

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import settings

_client: genai.Client | None = None


class EmbeddingError(Exception):
    """Raised when embedding cannot run (missing config, API failure, etc.)."""


class QuotaExceededError(EmbeddingError):
    """Raised when Gemini's rate limit or daily quota has been used up."""


def _quota_wait_hint(exc: Exception) -> str:
    """Pull a retry delay out of a 429's error body, if one is given."""
    match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)", str(exc))
    return f" Try again in about {match.group(1)}s." if match else ""


def _get_client() -> genai.Client:
    global _client
    if not settings.GEMINI_API_KEY:
        raise EmbeddingError(
            "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and fill it in (or export GEMINI_API_KEY)."
        )
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def embed_text(text: str, task_type: str = "RETRIEVAL_QUERY") -> list[float]:
    """Return an `EMBEDDING_DIM`-dim embedding vector for `text`."""
    client = _get_client()
    try:
        response = client.models.embed_content(
            model=settings.EMBEDDING_MODEL_NAME,
            contents=text,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=settings.EMBEDDING_DIM,
            ),
        )
    except genai_errors.APIError as exc:
        if exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED":
            raise QuotaExceededError(
                "Gemini's usage limit has been reached for now."
                + _quota_wait_hint(exc)
            ) from exc
        raise EmbeddingError(f"Gemini embedding request failed: {exc}") from exc
    except Exception as exc:
        raise EmbeddingError(f"Gemini embedding request failed: {exc}") from exc

    if not response.embeddings:
        raise EmbeddingError("Gemini returned no embedding.")
    return list(response.embeddings[0].values)
