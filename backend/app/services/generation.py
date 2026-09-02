"""
LLM generation service skeleton.

Given the retrieved/reranked chunks and the original question, assemble a
prompt and call the configured LLM provider, returning a cited answer.
Not implemented yet.
"""

from app.core.config import settings


def generate_answer(question: str, chunks: list[dict]) -> str:
    """Return an LLM-generated, cited answer. Not implemented yet."""
    raise NotImplementedError(
        f"Generation not implemented yet (provider configured: {settings.LLM_PROVIDER})"
    )
