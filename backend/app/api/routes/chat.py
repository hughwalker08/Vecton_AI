"""
Chat endpoint.

Flow (see planning doc, Part C - Query time):
    1. Embed the incoming question.
    2. Hybrid search (vector + BM25) against Supabase/pgvector.
    3. Rerank top results.
    4. If nothing relevant enough -> return "no source found" (abstain).
    5. Otherwise assemble prompt + top chunks and call the LLM.
    6. Return the cited answer.

Steps 1-3 are app.services.retrieval.retrieve(); step 5 is
app.services.generation.generate_answer().

Multi-turn: the caller sends prior conversation turns as `history` on each
request (the frontend keeps the chat's message list client-side -- there's
no server-side conversation storage). Retrieval only ever searches on the
current question; history is used for generation only, see
generation.py's module docstring for why.

A user can also attach one document to a chat (`attachment_name` /
`attachment_text`, extracted client-side by services/document_text.py via
/api/upload/) -- also resent every turn, also generation-only, not used for
retrieval.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.embedding import EmbeddingError
from app.services.embedding import QuotaExceededError as EmbeddingQuotaExceeded
from app.services.generation import GenerationError, generate_answer
from app.services.generation import QuotaExceededError as GenerationQuotaExceeded
from app.services.retrieval import QuotaExceededError as RerankQuotaExceeded
from app.services.retrieval import RerankError, retrieve

router = APIRouter()

# How many reranked chunks get sent to the LLM as context.
RETRIEVAL_TOP_K = 8

# Below this rerank score, even the best-matching chunk isn't considered a
# real match -- abstain instead of asking the LLM to make something of noise.
# Cross-encoder scores for genuinely on-topic clauses ran ~0.7-0.9998 and
# clearly-irrelevant text ~0.00004 in manual testing; this is a first cut and
# worth revisiting once there's real query traffic to calibrate against.
MIN_RERANK_SCORE = 0.1


Jurisdiction = Literal[
    "ACT",
    "NSW",
    "NT",
    "QLD",
    "SA",
    "TAS",
    "VIC",
    "WA",
]


class ChatTurn(BaseModel):
    """One prior message in the conversation, as shown in the chat UI --
    not the retrieval internals (no chunks/citations), just the plain text.
    See generation.generate_answer()'s docstring for how this is replayed."""

    role: Literal["user", "assistant"]
    text: str


class ChatRequest(BaseModel):
    question: str
    jurisdiction: Jurisdiction
    # Oldest first. Only the most recent messages are actually used (see
    # generation.MAX_HISTORY_MESSAGES) -- the frontend also trims what it
    # sends, but generate_answer() enforces the cap regardless of caller.
    history: list[ChatTurn] = []
    # A document the user attached to this chat (services/document_text.py
    # extracted it client-side, via /api/upload/, before this request). Resent
    # by the frontend on every turn of the chat -- nothing is persisted here.
    attachment_name: str | None = None
    attachment_text: str | None = None


class Citation(BaseModel):
    clause_id: str
    doc: str
    source_url: str | None = None
    # Populated from the same chunk dict app.services.generation._format_chunk
    # reads from -- carried through so the frontend's source panel can show
    # the clause without a second round trip.
    heading: str | None = None
    text: str | None = None
    building_classes: list[str] | None = None
    jurisdictions: list[str] | None = None
    climate_zones: list[int] | None = None
    applicability_note: str | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    abstained: bool = False


def _citations_from(chunks: list[dict]) -> list[Citation]:
    """One Citation per distinct (clause_id, doc), in relevance order."""
    seen: set[tuple[str, str | None]] = set()
    citations = []
    for chunk in chunks:
        clause_id, doc = chunk.get("clause_id"), chunk.get("doc")
        if not clause_id or (clause_id, doc) in seen:
            continue
        seen.add((clause_id, doc))
        citations.append(
            Citation(
                clause_id=clause_id,
                doc=doc or "",
                source_url=chunk.get("source_url"),
                heading=chunk.get("heading"),
                text=chunk.get("text"),
                building_classes=chunk.get("building_classes"),
                jurisdictions=chunk.get("jurisdictions"),
                climate_zones=chunk.get("climate_zones"),
                applicability_note=chunk.get("applicability_note"),
            )
        )
    return citations


@router.post("/", response_model=ChatResponse)
def ask_question(request: ChatRequest) -> ChatResponse:
    """Generate a cited answer for the chat UI, grounded in retrieved chunks."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    try:
        chunks = retrieve(question, top_k=RETRIEVAL_TOP_K, jurisdiction=request.jurisdiction)
    except (EmbeddingQuotaExceeded, RerankQuotaExceeded) as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (EmbeddingError, RerankError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not chunks or chunks[0]["rerank_score"] < MIN_RERANK_SCORE:
        return ChatResponse(answer="No source found.", citations=[], abstained=True)

    history = [{"role": turn.role, "text": turn.text} for turn in request.history]

    try:
        answer = generate_answer(
            question,
            chunks,
            jurisdiction=request.jurisdiction,
            history=history,
            attachment_name=request.attachment_name,
            attachment_text=request.attachment_text,
        )
    except GenerationQuotaExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not answer:
        return ChatResponse(answer="No source found.", citations=[], abstained=True)

    return ChatResponse(
        answer=answer,
        citations=_citations_from(chunks),
        abstained=False,
    )
