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
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.embedding import EmbeddingError
from app.services.embedding import QuotaExceededError as EmbeddingQuotaExceeded
from app.services.generation import GenerationError, generate_answer
from app.services.generation import QuotaExceededError as GenerationQuotaExceeded
from app.services.retrieval import RerankError, retrieve
from app.services.retrieval import QuotaExceededError as RerankQuotaExceeded

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


class ChatRequest(BaseModel):
    question: str
    jurisdiction: Jurisdiction


class Citation(BaseModel):
    clause_id: str
    doc: str
    source_url: str | None = None


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
            Citation(clause_id=clause_id, doc=doc or "", source_url=chunk.get("source_url"))
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

    try:
        answer = generate_answer(question, chunks, jurisdiction=request.jurisdiction)
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
