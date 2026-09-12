"""
Hybrid retrieval service skeleton.

Intended approach: dense (vector) search + lexical (BM25) search, fused
with Reciprocal Rank Fusion, then reranked down to a top-N before being
sent to the LLM. Not implemented yet.
"""

from sqlalchemy import or_

from app.models.clause_chunk import ClauseChunk

VALID_JURISDICTIONS = {
    "ACT",
    "NSW",
    "NT",
    "QLD",
    "SA",
    "TAS",
    "VIC",
    "WA",
}

def jurisdiction_filter(jurisdiction: str):
    """
    Return the SQLAlchemy filter for Australian jurisdiction routing.

    A user should receive:
    - clauses with no jurisdiction restriction (national clauses), OR
    - clauses that explicitly apply to the user's jurisdiction.

    Clauses specific to other jurisdictions are excluded.
    """
    jurisdiction = jurisdiction.upper()

    if jurisdiction not in VALID_JURISDICTIONS:
        raise ValueError(f"Unsupported jurisdiction: {jurisdiction}")

    return or_(
        ClauseChunk.jurisdictions.is_(None),
        ClauseChunk.jurisdictions.any(jurisdiction),
    )


def hybrid_search(query: str, top_k: int = 10) -> list[dict]:
    """Return the top_k most relevant clause chunks for the query. Not implemented yet."""
    raise NotImplementedError("Hybrid search not implemented yet.")


def rerank(query: str, candidates: list[dict], top_n: int = 10) -> list[dict]:
    """Rerank candidate chunks and keep the top_n. Not implemented yet."""
    raise NotImplementedError("Reranking not implemented yet.")
