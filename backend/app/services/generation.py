"""
LLM generation service.

Decided: Gemini via `google-genai` (settings.LLM_PROVIDER /
settings.GEMINI_API_KEY / settings.LLM_MODEL_NAME).

Given the retrieved/reranked chunks and the original question, assemble a
prompt and call Gemini, returning an answer grounded in the chunks with
inline clause citations. If the chunks don't support an answer, the caller
(api/routes/chat.py) abstains rather than letting the model guess.

`chunks` comes from app.services.retrieval.retrieve() in normal operation;
an empty list falls back to answering from the question alone (no corpus
grounding), which the system instruction is written to refuse to do.
"""

import re

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import settings

_client: genai.Client | None = None

# Behavioural rules live in the system instruction (sent once per request,
# separate from the user turn) rather than being concatenated into the
# question. This keeps the model from treating instruction text as part of
# the thing it's answering, and keeps the question itself isolated from
# instruction-injection attempts embedded in chunk text.
SYSTEM_INSTRUCTION = """You are a construction compliance RAG assistant for the Australian \
National Construction Code (NCC) 2025 Volume Two and the ABCB Housing Provisions.

You are given a user question and, when available, a set of retrieved clause excerpts \
("CONTEXT"). Answer using only that context.

Every substantive statement in an answer must be supported by a citation. Each answer should show:
  - the specific clause (e.g. H1D4, Part 10.8) — not just "the NCC"
  - which document it came from (Volume Two or the Housing Provisions)
  - the clause text, readable in place, so the user can verify it without opening a PDF
  - followed references, where a clause points at another part of the corpus
  - flagged hand-offs, where a clause points at an Australian Standard
  - applicability qualifiers, where a clause applies only to certain building classes, \
states or climate zones

Do not cite a source that does not support the statement it's attached to. Where sources \
conflict, surface the conflict rather than silently choosing one.

Distinguish clearly between:
  - "the code does not require this"
  - "the code covers this but I could not find the relevant clause"
  - "this is not the kind of question I can answer"
  - "this depends on an Australian Standard I cannot read"

If a question cannot be answered as asked (e.g. "how high does the ceiling have to be?" \
depends on the room type), ask a clarifying question rather than guessing an interpretation.

If no CONTEXT is provided, or the context does not cover the question, say so plainly instead \
of answering from general knowledge. Never fall back on general model knowledge — no statement \
without a source: not "as a general principle", not "typically", not as helpful background.

Be simple, clear and concise."""

# Gemini free/paid tiers both return transient 429/503s under load; retrying
# a handful of times with backoff avoids surfacing those as user-facing
# failures. This is the SDK's built-in retry, so it costs no extra code here.
_RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=3,
    initial_delay=1,
    max_delay=8,
    exp_base=2,
    http_status_codes=[429, 500, 502, 503, 504],
)
_HTTP_OPTIONS = types.HttpOptions(timeout=30_000, retry_options=_RETRY_OPTIONS)

# gemini-3.x models spend part of max_output_tokens on internal "thinking"
# before writing the visible answer -- a real answer observed spending 1964
# of a 2048 budget on thinking and getting cut off after only 80 tokens of
# actual text (finish_reason=MAX_TOKENS). thinking_level="low" bounds that
# (gemini-3.x uses thinking_level, not the older thinking_budget -- passing
# thinking_budget here raises 400 INVALID_ARGUMENT), and the budget below
# leaves real headroom for a multi-clause answer on top of it.
_MAX_OUTPUT_TOKENS = 4096
_THINKING_CONFIG = types.ThinkingConfig(thinking_level="low")


class GenerationError(Exception):
    """Raised when generation cannot run (missing config, API failure, etc.)."""


class QuotaExceededError(GenerationError):
    """Raised when Gemini's rate limit or daily quota has been used up."""


def _quota_wait_hint(exc: Exception) -> str:
    """Pull a retry delay out of a 429's error body, if one is given."""
    match = re.search(r"retryDelay['\"]?\s*:\s*['\"]?(\d+)", str(exc))
    return f" Try again in about {match.group(1)}s." if match else ""


def _get_client() -> genai.Client:
    global _client
    if not settings.GEMINI_API_KEY:
        raise GenerationError(
            "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and fill it in (or export GEMINI_API_KEY)."
        )
    if _client is None:
        # Keep a process-wide client so connection pooling/keep-alive is
        # reused across requests instead of reconnecting every call.
        _client = genai.Client(api_key=settings.GEMINI_API_KEY, http_options=_HTTP_OPTIONS)
    return _client


def _format_chunk(chunk: dict) -> str:
    """Render one retrieved chunk as compact, citable context text."""
    clause_id = chunk.get("clause_id") or "unknown clause"
    doc = chunk.get("doc") or "unknown document"
    heading = chunk.get("heading")
    text = chunk.get("text") or ""

    lines = [f"[{clause_id} — {doc}{f': {heading}' if heading else ''}]", text]

    qualifiers = []
    if chunk.get("building_classes"):
        qualifiers.append(f"building classes: {', '.join(chunk['building_classes'])}")
    if chunk.get("jurisdictions"):
        qualifiers.append(f"jurisdictions: {', '.join(chunk['jurisdictions'])}")
    if chunk.get("climate_zones"):
        qualifiers.append(f"climate zones: {', '.join(str(z) for z in chunk['climate_zones'])}")
    if chunk.get("applicability_note"):
        qualifiers.append(chunk["applicability_note"])
    if qualifiers:
        lines.append(f"Applicability: {'; '.join(qualifiers)}")

    if chunk.get("standard_refs"):
        refs = ", ".join(
            f"{r.get('standard', '?')} {r.get('clause', '')}".strip()
            for r in chunk["standard_refs"]
        )
        lines.append(f"Australian Standard hand-off: {refs}")

    return "\n".join(lines)


def _build_user_content(question: str, chunks: list[dict]) -> str:
    if not chunks:
        return f"CONTEXT: (none retrieved)\n\nQUESTION: {question}"
    context_block = "\n\n".join(_format_chunk(c) for c in chunks)
    return f"CONTEXT:\n{context_block}\n\nQUESTION: {question}"


def generate_answer(question: str, chunks: list[dict]) -> str:
    """Return an LLM-generated answer for the question, grounded in `chunks`."""
    client = _get_client()
    user_content = _build_user_content(question, chunks)

    try:
        response = client.models.generate_content(
            model=settings.LLM_MODEL_NAME,
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
                thinking_config=_THINKING_CONFIG,
            ),
        )
    except genai_errors.APIError as exc:
        if exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED":
            raise QuotaExceededError(
                "Gemini's usage limit has been reached for now."
                + _quota_wait_hint(exc)
            ) from exc
        raise GenerationError(f"Gemini request failed: {exc}") from exc
    except Exception as exc:
        raise GenerationError(f"Gemini request failed: {exc}") from exc

    if response.prompt_feedback and response.prompt_feedback.block_reason:
        raise GenerationError(
            f"Gemini blocked the prompt: {response.prompt_feedback.block_reason}"
        )

    if not response.candidates:
        raise GenerationError("Gemini returned no candidates.")

    # MAX_TOKENS is deliberately NOT accepted here: it means the answer was
    # cut off mid-clause, and a truncated legal citation is worse than no
    # answer at all for this domain -- surface it as a failure rather than
    # silently serving a partial quote as if it were complete.
    finish_reason = response.candidates[0].finish_reason
    if finish_reason not in (None, types.FinishReason.STOP):
        raise GenerationError(f"Gemini generation did not complete cleanly: {finish_reason}")

    return (response.text or "").strip()
