"""
Embedding service skeleton.

Decision pending: BGE-M3 (self-hosted) vs Gemini embeddings (API, free tier).
Swap the implementation once that's decided; keep this function signature
stable so callers don't need to change.
"""

from app.core.config import settings


def embed_text(text: str) -> list[float]:
    """Return an embedding vector for the given text. Not implemented yet."""
    raise NotImplementedError(
        f"Embedding not implemented yet (provider configured: {settings.EMBEDDING_PROVIDER})"
    )
