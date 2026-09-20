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

Multi-turn: `generate_answer()` optionally takes prior conversation turns
(`history`) and replays them ahead of the current question, Gemini-chat
style, so a follow-up like "what about NSW?" is understood in context. This
only affects generation -- retrieval always searches on the raw current
question alone (see api/routes/chat.py), since a bare follow-up like that
retrieves poorly on its own; a query-condensation step is a known future
improvement, not implemented here.

A user can also attach one document to a chat (`attachment_name`/
`attachment_text`) -- folded in as a second, explicitly-labelled source
(never cited as if it were a code clause) via `_ATTACHMENT_ADDENDUM`.

Every call is retried across the pooled Gemini API keys in
`settings.gemini_api_keys` (see services/gemini_keys.py) before a quota
error is surfaced to the caller -- see call_with_rotation()'s docstring for
the rotation strategy.
"""

from __future__ import annotations

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from app.core.config import settings
from app.services.gemini_keys import call_with_rotation, quota_wait_hint

_clients: dict[str, genai.Client] = {}

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

Be simple, clear and concise.

Formatting: plain text only, never Markdown -- the chat UI displays your answer as raw text, so \
Markdown syntax would show up as literal asterisks and hashes instead of being rendered. \
Concretely: no **bold**/*italic* markers, no # / ## headings, no > blockquotes, no `code` \
fences, no [link](url) syntax. For a heading or clause label, just write it as its own line \
followed by a colon (e.g. "Clause H1D4 -- NCC 2025 Volume Two:"). For a list, use a plain dash \
or number ("- " or "1. ") at the start of the line. For quoted clause text, introduce it with a \
line like "Clause text:" and put the quote on its own line rather than using a > blockquote. \
Separate sections and list items with a blank line so they render as distinct paragraphs."""

# Jurisdiction is collected from the user up front (see api/routes/chat.py:
# ChatRequest.jurisdiction) and appended here per-request rather than baked
# into the static instruction above, since it varies by caller.
_JURISDICTION_ADDENDUM = """

The user has told you their jurisdiction: {jurisdiction}. A clause with no jurisdiction \
qualifier applies nationally. A clause qualified for a specific jurisdiction applies only if \
it names {jurisdiction} — say plainly when a retrieved clause does not apply to the user's \
jurisdiction rather than citing it as if it did, and note when a national requirement is \
varied or replaced by a {jurisdiction}-specific one."""

# The user can attach their own document to a chat (see api/routes/chat.py's
# attachment_text) -- a design spec, drawing-set transcription, or building
# report, extracted client-side via services/document_text.py. It's a second
# source, not a corpus clause, so it needs an explicit carve-out from "every
# statement needs a citation": otherwise the model either refuses to use it or
# mislabels it as a code citation.
_ATTACHMENT_ADDENDUM = """

The user has attached their own document to this chat, named "{name}" (given to you below as \
ATTACHED DOCUMENT). You may use it as a second source: describe what it says and compare it \
against the CONTEXT clauses. Attribute any statement drawn from it to the document by name \
(e.g. "{name} states..."), never as a code citation — it is evidence about the user's project, \
not a source for what the code requires. Only CONTEXT establishes what the NCC/ABCB requires."""


def _build_system_instruction(jurisdiction: str | None, attachment_name: str | None = None) -> str:
    instruction = SYSTEM_INSTRUCTION
    if jurisdiction:
        instruction += _JURISDICTION_ADDENDUM.format(jurisdiction=jurisdiction)
    if attachment_name:
        instruction += _ATTACHMENT_ADDENDUM.format(name=attachment_name)
    return instruction

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
try:
    _THINKING_CONFIG = types.ThinkingConfig(thinking_level="low")
except ValidationError:
    # TESTING NOTE (found while adding Phase 0 test scaffolding): the
    # installed google-genai SDK (checked up to 1.47.0, the latest on PyPI)
    # doesn't expose thinking_level on ThinkingConfig yet, so building this
    # at import time raised pydantic's "extra_forbidden" and crashed the
    # entire app before it could even serve /health. Falling back to no
    # thinking config keeps the app importable; whoever owns generation.py
    # should follow up on the real fix (SDK upgrade, or the dict-based
    # config path) once one exists -- this is not a fix for the underlying
    # MAX_TOKENS truncation issue described above.
    _THINKING_CONFIG = None


class GenerationError(Exception):
    """Raised when generation cannot run (missing config, API failure, etc.)."""


class QuotaExceededError(GenerationError):
    """Raised when Gemini's rate limit or daily quota has been used up."""


def _is_quota_error(exc: Exception) -> bool:
    return isinstance(exc, genai_errors.APIError) and (
        exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED"
    )


def _client_for(key: str) -> genai.Client:
    # Keep one client per key, process-wide, so connection pooling/keep-alive
    # is reused across requests instead of reconnecting every call.
    if key not in _clients:
        _clients[key] = genai.Client(api_key=key, http_options=_HTTP_OPTIONS)
    return _clients[key]


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


def _build_user_content(
    question: str,
    chunks: list[dict],
    attachment_name: str | None = None,
    attachment_text: str | None = None,
) -> str:
    context_block = "\n\n".join(_format_chunk(c) for c in chunks) if chunks else "(none retrieved)"
    parts = [f"CONTEXT:\n{context_block}"]
    if attachment_text:
        parts.append(f"ATTACHED DOCUMENT ({attachment_name}):\n{attachment_text}")
    parts.append(f"QUESTION: {question}")
    return "\n\n".join(parts)


# How many prior turns (user+assistant messages, not exchanges) get replayed
# ahead of the current question -- the chat-memory equivalent of
# RETRIEVAL_TOP_K/MIN_RERANK_SCORE in api/routes/chat.py: a first cut, not a
# hard technical ceiling. Gemini's context window is far bigger than this;
# the constraint is per-request latency/cost, which scales with how much of
# the conversation gets re-sent on every turn. Enforced here (not just by the
# caller) so generate_answer() is safe to call with an unbounded history.
MAX_HISTORY_MESSAGES = 6

# Gemini's multi-turn roles are "user" and "model" -- not the "assistant"
# label the frontend/chat.py use (matching OpenAI-style chat conventions).
_ROLE_TO_GEMINI = {"user": "user", "assistant": "model"}


def _history_contents(history: list[dict] | None) -> list[types.Content]:
    """Prior turns (oldest first) as Gemini Content objects, most recent
    MAX_HISTORY_MESSAGES only. Each turn is replayed as the plain text the
    user saw -- the CONTEXT block built by _build_user_content() is only
    attached to the *current* turn below, not stored per-turn, since the
    model already generated its earlier answers with that context in view."""
    if not history:
        return []
    trimmed = history[-MAX_HISTORY_MESSAGES:]
    return [
        types.Content(role=_ROLE_TO_GEMINI.get(turn["role"], "user"), parts=[types.Part(text=turn["text"])])
        for turn in trimmed
        if turn.get("text")
    ]


def generate_answer(
    question: str,
    chunks: list[dict],
    jurisdiction: str | None = None,
    history: list[dict] | None = None,
    attachment_name: str | None = None,
    attachment_text: str | None = None,
) -> str:
    """Return an LLM-generated answer for the question, grounded in `chunks`.

    `jurisdiction` (e.g. "NSW"), when known, is folded into the system
    instruction so the model applies jurisdiction-qualified clauses correctly
    instead of just citing whatever the context happens to contain.

    `history` is prior conversation turns, oldest first, each
    {"role": "user"|"assistant", "text": str} -- the plain question/answer
    text as shown in the chat UI, not the retrieval internals. Only the most
    recent MAX_HISTORY_MESSAGES are replayed; retrieval itself (see
    api/routes/chat.py) does not use history, only the raw current question.

    `attachment_text`, when given, is a document the user attached to the
    chat (see api/routes/chat.py) -- a second source, folded into both the
    user content and the system instruction so the model treats it as
    project evidence rather than a corpus citation.
    """
    if not settings.gemini_api_keys:
        raise GenerationError(
            "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and fill it in (or export GEMINI_API_KEY / GEMINI_API_KEYS)."
        )
    attachment_text = (attachment_text or "").strip() or None
    attachment_label = (attachment_name or "the attached document") if attachment_text else None
    user_content = _build_user_content(question, chunks, attachment_label, attachment_text)
    contents = _history_contents(history) + [
        types.Content(role="user", parts=[types.Part(text=user_content)])
    ]

    def _call(key: str):
        client = _client_for(key)
        try:
            return client.models.generate_content(
                model=settings.LLM_MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=_build_system_instruction(jurisdiction, attachment_label),
                    temperature=0,
                    max_output_tokens=_MAX_OUTPUT_TOKENS,
                    thinking_config=_THINKING_CONFIG,
                ),
            )
        except genai_errors.APIError as exc:
            if _is_quota_error(exc):
                raise
            raise GenerationError(f"Gemini request failed: {exc}") from exc
        except Exception as exc:
            raise GenerationError(f"Gemini request failed: {exc}") from exc

    try:
        response = call_with_rotation(_is_quota_error, _call)
    except genai_errors.APIError as exc:
        raise QuotaExceededError(
            "Gemini's usage limit has been reached for now." + quota_wait_hint(exc)
        ) from exc

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
