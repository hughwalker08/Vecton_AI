"""
Embedding service skeleton.

Decided: Gemini embeddings via `google-generativeai`, model
`text-embedding-004`, 768-dim output (settings.EMBEDDING_MODEL_NAME /
settings.EMBEDDING_DIM). Keep this function signature stable so callers
don't need to change when the implementation lands.

Implementation notes:
  - Use task_type="RETRIEVAL_DOCUMENT" when embedding corpus/upload chunks
    and task_type="RETRIEVAL_QUERY" when embedding a user question.
  - Batch calls where possible; respect Gemini free-tier rate limits.
"""

from app.core.config import settings


def embed_text(text: str) -> list[float]:
    """Return a 768-dim embedding vector for the given text. Not implemented yet."""
    raise NotImplementedError(
        f"Embedding not implemented yet "
        f"(provider: {settings.EMBEDDING_PROVIDER}, model: {settings.EMBEDDING_MODEL_NAME})"
    )
