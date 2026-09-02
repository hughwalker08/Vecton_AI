"""
Chat endpoint skeleton.

Intended flow (see planning doc, Part C - Query time):
    1. Embed the incoming question.
    2. Hybrid search (vector + BM25) against Supabase/pgvector.
    3. Rerank top results.
    4. If nothing relevant enough -> return "no source found" (abstain).
    5. Otherwise assemble prompt + top chunks and call the LLM.
    6. Return the cited answer.

None of this is implemented yet - just the route shape and schema.
"""

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ChatRequest(BaseModel):
    question: str


class Citation(BaseModel):
    clause_id: str
    doc: str
    source_url: str | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    abstained: bool = False


@router.post("/", response_model=ChatResponse)
def ask_question(request: ChatRequest) -> ChatResponse:
    """Placeholder - not yet wired up to retrieval or generation."""
    return ChatResponse(
        answer="Not implemented yet.",
        citations=[],
        abstained=True,
    )
