"""
Compliance analysis engine.

Roadmap item: "Document-to-requirement analysis (findings: missing /
contradicted / addressed / needs review)".

Given a document's text and a description of what it's for (`query`, e.g.
"Class 1a dwelling stormwater drainage and smoke alarm requirements"), this
finds the NCC/ABCB clauses that apply (app.services.retrieval.retrieve(),
the same hybrid-search-then-rerank path chat.py uses) and asks Gemini to
classify each one against the document, in a single structured-output call:

  - "addressed"     -- the document states something that satisfies it.
  - "contradicted"  -- the document states something that conflicts with it.
  - "missing"       -- the requirement isn't mentioned in the document at all.
  - "needs_review"  -- not enough information to decide -- a human should look.

api/routes/upload.py's text extraction (LlamaParse for PDF, python-docx for
DOCX) is not wired up yet, so `analyse_document()` takes already-extracted
`document_text` directly rather than a file. Once that pipeline exists, it
becomes this module's caller.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.services.gemini_keys import call_with_rotation, quota_wait_hint
from app.services.retrieval import retrieve

Status = Literal["addressed", "missing", "contradicted", "needs_review"]
STATUSES: tuple[Status, ...] = ("addressed", "missing", "contradicted", "needs_review")

_clients: dict[str, genai.Client] = {}

SYSTEM_INSTRUCTION = """You are a construction compliance analysis engine for the Australian \
National Construction Code (NCC) 2025 Volume Two and the ABCB Housing Provisions.

You are given a set of REQUIREMENT clauses, each identified by a clause_id, and the text of a \
submitted DOCUMENT (a design specification, drawing-set transcription, or building report). For \
every REQUIREMENT clause, decide how the DOCUMENT relates to it and classify it into exactly one \
of:

  - "addressed" -- the document explicitly states something that satisfies the requirement.
  - "contradicted" -- the document explicitly states something that conflicts with the requirement.
  - "missing" -- the requirement's subject is not mentioned anywhere in the document.
  - "needs_review" -- the document touches on the requirement's subject but there isn't enough \
information to say whether it's satisfied, or the wording is ambiguous -- a human should check \
this one.

Rules:
  - Classify every clause you're given, exactly once each. Do not skip one, and do not invent a \
clause_id that wasn't given to you.
  - Base every classification only on the DOCUMENT text and the REQUIREMENT text -- never on \
general knowledge of the NCC or construction practice.
  - "evidence" must be a short verbatim quote from the DOCUMENT supporting the classification, or \
null when nothing in the document addresses it (i.e. for "missing").
  - "explanation" is one or two plain sentences saying why, tied to the requirement's actual \
content -- not just "clause X requires Y".
  - Respect each requirement's applicability qualifiers (building class, jurisdiction, climate \
zone) if given; if the document is clearly for a project the clause doesn't apply to, say so in \
the explanation and classify it "needs_review" rather than guessing.
  - When in doubt between "addressed" and "needs_review", choose "needs_review" -- a false \
"addressed" is worse than an extra item for the reviewer to check.
  - When in doubt between "missing" and "needs_review", choose "needs_review" if the document \
mentions the general topic at all, even loosely; choose "missing" only if the topic doesn't \
appear.
  - Don't default to "needs_review" just to hedge. If the document states a specific fact -- a \
number, a material, a yes/no -- that fails the requirement's actual threshold, that is \
"contradicted", full stop, even if the document doesn't address every qualifier of the \
requirement. Reserve "needs_review" for when the document's wording is genuinely ambiguous or \
incomplete, not for cases where you can already say what's wrong with it -- if your own \
explanation states the document's value doesn't meet the requirement, the status must be \
"contradicted", not "needs_review"."""

# Same retry/thinking-budget handling as app.services.generation -- each
# Gemini-calling service module keeps its own copy rather than sharing one,
# matching how services/embedding.py and services/retrieval.py already do.
_RETRY_OPTIONS = types.HttpRetryOptions(
    attempts=3,
    initial_delay=1,
    max_delay=8,
    exp_base=2,
    http_status_codes=[429, 500, 502, 503, 504],
)
_HTTP_OPTIONS = types.HttpOptions(timeout=60_000, retry_options=_RETRY_OPTIONS)

# A findings list is bigger than a chat answer (one object per clause), so
# this gets more headroom than generation.py's chat budget.
_MAX_OUTPUT_TOKENS = 8192
try:
    _THINKING_CONFIG = types.ThinkingConfig(thinking_level="low")
except ValidationError:
    # See services/generation.py's matching note: older google-genai SDKs
    # don't expose thinking_level yet, and building this at import time would
    # otherwise crash the whole app before it could serve /health.
    _THINKING_CONFIG = None


class ComplianceAnalysisError(Exception):
    """Raised when compliance analysis cannot run (missing config, API failure, etc.)."""


class QuotaExceededError(ComplianceAnalysisError):
    """Raised when Gemini's rate limit or daily quota has been used up."""


def _is_quota_error(exc: Exception) -> bool:
    return isinstance(exc, genai_errors.APIError) and (
        exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED"
    )


def _client_for(key: str) -> genai.Client:
    if key not in _clients:
        _clients[key] = genai.Client(api_key=key, http_options=_HTTP_OPTIONS)
    return _clients[key]


@dataclass
class ComplianceFinding:
    """One requirement clause's classification against a document."""

    clause_id: str
    doc: str
    status: Status
    explanation: str
    heading: str | None = None
    evidence: str | None = None
    source_url: str | None = None


@dataclass
class ComplianceReport:
    query: str
    jurisdiction: str | None = None
    findings: list[ComplianceFinding] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        """Findings grouped by status, every status present even at zero."""
        counts = dict.fromkeys(STATUSES, 0)
        for finding in self.findings:
            counts[finding.status] += 1
        return counts


class _FindingLLM(BaseModel):
    """Structured-output shape Gemini is asked to return, one per requirement."""

    clause_id: str
    status: Status
    explanation: str
    evidence: str | None = None


def _dedupe_chunks(chunks: list[dict]) -> list[dict]:
    """One chunk per distinct (clause_id, doc), in relevance order.

    A long clause is split across multiple embedded chunks (see
    app/ingest/chunker.py), so retrieve() can return the same clause_id more
    than once -- api/routes/chat.py's _citations_from() already guards
    against this for chat citations; analyse_document() needs the same
    guard, or a clause with several chunks gets classified and reported as
    two, three, or more identical findings instead of one.
    """
    seen: set[tuple[str, str | None]] = set()
    deduped = []
    for chunk in chunks:
        clause_id, doc = chunk.get("clause_id"), chunk.get("doc")
        if not clause_id or (clause_id, doc) in seen:
            continue
        seen.add((clause_id, doc))
        deduped.append(chunk)
    return deduped


def _format_requirement(chunk: dict) -> str:
    """Render one retrieved clause as labelled REQUIREMENT text for the prompt."""
    clause_id = chunk.get("clause_id") or "unknown clause"
    doc = chunk.get("doc") or "unknown document"
    heading = chunk.get("heading")
    text = chunk.get("text") or ""

    lines = [f"[clause_id: {clause_id} -- {doc}{f': {heading}' if heading else ''}]", text]

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

    return "\n".join(lines)


def _build_user_content(document_text: str, chunks: list[dict]) -> str:
    requirements_block = "\n\n".join(_format_requirement(c) for c in chunks)
    return f"REQUIREMENTS:\n{requirements_block}\n\nDOCUMENT:\n{document_text}"


def _classify(document_text: str, chunks: list[dict]) -> dict[str, _FindingLLM]:
    """Ask Gemini to classify every clause in `chunks` against `document_text`.

    Returns the results keyed by clause_id; a clause the model didn't return
    simply won't be a key, which the caller turns into a "needs_review"
    finding rather than dropping it.
    """
    if not settings.gemini_api_keys:
        raise ComplianceAnalysisError(
            "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and fill it in (or export GEMINI_API_KEY / GEMINI_API_KEYS)."
        )
    user_content = _build_user_content(document_text, chunks)

    def _call(key: str):
        client = _client_for(key)
        try:
            return client.models.generate_content(
                model=settings.LLM_MODEL_NAME,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0,
                    max_output_tokens=_MAX_OUTPUT_TOKENS,
                    thinking_config=_THINKING_CONFIG,
                    response_mime_type="application/json",
                    response_schema=list[_FindingLLM],
                ),
            )
        except genai_errors.APIError as exc:
            if _is_quota_error(exc):
                raise
            raise ComplianceAnalysisError(f"Gemini request failed: {exc}") from exc
        except Exception as exc:
            raise ComplianceAnalysisError(f"Gemini request failed: {exc}") from exc

    try:
        response = call_with_rotation(_is_quota_error, _call)
    except genai_errors.APIError as exc:
        raise QuotaExceededError(
            "Gemini's usage limit has been reached for now." + quota_wait_hint(exc)
        ) from exc

    if response.prompt_feedback and response.prompt_feedback.block_reason:
        raise ComplianceAnalysisError(
            f"Gemini blocked the prompt: {response.prompt_feedback.block_reason}"
        )
    if not response.candidates:
        raise ComplianceAnalysisError("Gemini returned no candidates.")

    # Same stance as generation.py: a cut-off classification pass is worse
    # than surfacing the failure, since it silently drops clauses instead of
    # falling them through to "needs_review".
    finish_reason = response.candidates[0].finish_reason
    if finish_reason not in (None, types.FinishReason.STOP):
        raise ComplianceAnalysisError(f"Gemini generation did not complete cleanly: {finish_reason}")

    results = response.parsed
    if not results:
        # Defensive fallback in case the SDK didn't populate .parsed even
        # though we asked for structured JSON -- parse response.text by hand.
        try:
            results = [_FindingLLM.model_validate(item) for item in json.loads(response.text or "[]")]
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            raise ComplianceAnalysisError(
                f"Could not parse Gemini's classification response: {exc}"
            ) from exc

    return {item.clause_id: item for item in results}


def analyse_document(
    document_text: str,
    query: str,
    jurisdiction: str | None = None,
    top_k: int = 10,
) -> ComplianceReport:
    """Classify the requirement clauses applicable to `query` against `document_text`.

    `query` describes what the document is for (e.g. a summary of the
    project or the topics it should cover) -- it's what retrieval.retrieve()
    searches with to find the applicable clauses. `jurisdiction`, when
    given, restricts those clauses the same way it does in chat.py.
    """
    document_text = (document_text or "").strip()
    if not document_text:
        raise ValueError("document_text must not be empty.")
    query = (query or "").strip()
    if not query:
        raise ValueError("query must not be empty.")

    chunks = _dedupe_chunks(retrieve(query, top_k=top_k, jurisdiction=jurisdiction))
    report = ComplianceReport(query=query, jurisdiction=jurisdiction)
    if not chunks:
        return report

    by_clause_id = _classify(document_text, chunks)

    for chunk in chunks:
        clause_id = chunk.get("clause_id")
        result = by_clause_id.get(clause_id) if clause_id else None
        if result is None:
            report.findings.append(
                ComplianceFinding(
                    clause_id=clause_id or "unknown clause",
                    doc=chunk.get("doc") or "",
                    heading=chunk.get("heading"),
                    status="needs_review",
                    explanation=(
                        "The analysis engine did not return a classification for this "
                        "clause -- review it manually."
                    ),
                    source_url=chunk.get("source_url"),
                )
            )
            continue
        report.findings.append(
            ComplianceFinding(
                clause_id=clause_id,
                doc=chunk.get("doc") or "",
                heading=chunk.get("heading"),
                status=result.status,
                explanation=result.explanation,
                evidence=result.evidence,
                source_url=chunk.get("source_url"),
            )
        )

    return report
