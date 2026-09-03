"""
LLM generation service skeleton.

Decided: Gemini via `google-generativeai` (settings.LLM_PROVIDER /
settings.GEMINI_API_KEY).

Given the retrieved/reranked chunks and the original question, assemble a
prompt and call Gemini, returning an answer grounded in the chunks with
inline clause citations. If the chunks don't support an answer, the caller
(api/routes/chat.py) abstains rather than letting the model guess.
Not implemented yet.
"""

from app.core.config import settings


def generate_answer(question: str, chunks: list[dict]) -> str:
    """Return an LLM-generated, cited answer. Not implemented yet."""
    raise NotImplementedError(
        f"Generation not implemented yet (provider configured: {settings.LLM_PROVIDER})"
    )
