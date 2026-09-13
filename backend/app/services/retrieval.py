"""
Retrieval layer: search the vector store + knowledge base for the chunks
relevant to a user's question.

Two stages:

  1. Hybrid search (`hybrid_search`) -- dense (pgvector cosine) + lexical
     (Postgres full-text / BM25-style) search, fused with Reciprocal Rank
     Fusion (RRF), as documented in
     migrations/versions/0003_fulltext_tsvector.py. Cheap, casts a wide net.

  2. Rerank (`rerank`) -- a cross-encoder second pass (BAAI/bge-reranker-base,
     via the Hugging Face Inference router) that scores each candidate
     against the actual query text and reorders by true relevance, catching
     cases where the fused hybrid score picked up the wrong candidate.

`retrieve()` runs both stages and is the entry point callers should use.
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.db.session import engine
from app.services.embedding import embed_text

# Candidates considered per method (dense, lexical) before RRF fusion. Wider
# than what's returned so RRF has real signal to work with; cheap because
# both indexes (HNSW, GIN) make this a fast top-N scan, not a table scan.
CANDIDATE_POOL = 50

# Standard RRF constant (dampens the impact of a #1 rank vs #2..#k).
RRF_K = 60

# How many fused candidates get passed into the reranker by default.
RERANK_CANDIDATE_POOL = 30

VALID_JURISDICTIONS = {"ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA"}

_HF_ROUTER_URL = "https://router.huggingface.co/hf-inference/models/{model}"

# BAAI/bge-reranker-base (XLM-RoBERTa-based) caps at 512 tokens for the
# query+passage pair combined. Whole-Part/Specification chunks run 10k+
# chars, and NCC/ABCB clause text tokenizes far denser than plain English
# (numbers, clause refs, symbols -- observed as low as ~2 chars/token, not a
# safe thing to guess from character count). Let the model's own tokenizer
# truncate instead of estimating a character cutoff ourselves.
RERANKER_MAX_LENGTH = 512


class RerankError(Exception):
    """Raised when the reranker cannot run (missing config, API failure, etc.)."""


class QuotaExceededError(RerankError):
    """Raised when the Hugging Face Inference rate limit has been used up."""


def _to_vector_literal(vec: list[float]) -> str:
    """Render a Python vector as pgvector's text input format: '[0.1,0.2,...]'."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


# Jurisdiction routing: a user should see clauses with no jurisdiction
# restriction (national, jurisdictions IS NULL) plus clauses that explicitly
# name their jurisdiction -- never clauses restricted to a different one.
# :jurisdiction is bound to NULL when the caller doesn't filter by it, which
# short-circuits the whole clause to TRUE (no-op) rather than excluding rows.
_JURISDICTION_CLAUSE = """
        AND (
            :jurisdiction IS NULL
            OR jurisdictions IS NULL
            OR :jurisdiction = ANY(jurisdictions)
        )"""

_SEARCH_SQL = f"""
    WITH dense AS (
        SELECT id, row_number() OVER (ORDER BY embedding <=> :qvec) AS rank
        FROM clause_chunks
        WHERE embedding IS NOT NULL{_JURISDICTION_CLAUSE}
        ORDER BY embedding <=> :qvec
        LIMIT :pool
    ),
    lexical AS (
        SELECT id, row_number() OVER (
            ORDER BY ts_rank_cd(text_tsv, plainto_tsquery('english', :q)) DESC
        ) AS rank
        FROM clause_chunks
        WHERE text_tsv @@ plainto_tsquery('english', :q){_JURISDICTION_CLAUSE}
        ORDER BY ts_rank_cd(text_tsv, plainto_tsquery('english', :q)) DESC
        LIMIT :pool
    ),
    fused AS (
        SELECT id, SUM(1.0 / (:rrf_k + rank)) AS score
        FROM (SELECT * FROM dense UNION ALL SELECT * FROM lexical) both_methods
        GROUP BY id
    )
    SELECT
        c.clause_id, c.doc, c.heading, c.text, c.source_url,
        c.building_classes, c.jurisdictions, c.climate_zones,
        c.applicability_note, c.standard_refs,
        f.score AS fused_score
    FROM fused f
    JOIN clause_chunks c ON c.id = f.id
    ORDER BY f.score DESC
    LIMIT :top_k
"""

def hybrid_search(query: str, top_k: int = 10, jurisdiction: str | None = None) -> list[dict]:
    """Return the top_k candidates for `query` via fused dense + lexical search.

    `jurisdiction` (e.g. "NSW"), when given, restricts results to clauses with
    no jurisdiction restriction plus clauses naming that jurisdiction; clauses
    scoped to a different jurisdiction are excluded. Omit it to search the
    whole corpus.

    Each result is shaped for app.services.generation._format_chunk (clause_id,
    doc, heading, text, building_classes, jurisdictions, climate_zones,
    applicability_note, standard_refs), plus a `fused_score` for debugging.
    """
    from sqlalchemy import text as sql_text

    if jurisdiction is not None:
        jurisdiction = jurisdiction.upper()
        if jurisdiction not in VALID_JURISDICTIONS:
            raise ValueError(f"Unsupported jurisdiction: {jurisdiction}")

    qvec = embed_text(query, task_type="RETRIEVAL_QUERY")

    with engine.connect() as conn:
        rows = conn.execute(
            sql_text(_SEARCH_SQL),
            {
                "qvec": _to_vector_literal(qvec),
                "q": query,
                "pool": CANDIDATE_POOL,
                "rrf_k": RRF_K,
                "top_k": top_k,
                "jurisdiction": jurisdiction,
            },
        ).mappings().all()

    return [dict(row) for row in rows]


def rerank(query: str, candidates: list[dict], top_n: int = 10) -> list[dict]:
    """Reorder `candidates` by true relevance to `query` using a cross-encoder
    (BAAI/bge-reranker-base) and return the top_n.

    One HF Inference call scores every candidate against the query in a
    single batched request. Adds a `rerank_score` key to each returned dict.
    """
    if not candidates:
        return []
    if not settings.HF_API_TOKEN:
        raise RerankError(
            "HF_API_TOKEN is not set. Add it to backend/.env "
            "(https://huggingface.co/settings/tokens, needs 'Inference Providers' permission)."
        )

    url = _HF_ROUTER_URL.format(model=settings.RERANKER_MODEL_NAME)
    payload = {
        "inputs": [
            {"text": query, "text_pair": c.get("text") or ""} for c in candidates
        ],
        "parameters": {"truncation": True, "max_length": RERANKER_MAX_LENGTH},
    }

    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.HF_API_TOKEN}"},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            retry_after = exc.response.headers.get("retry-after")
            raise QuotaExceededError(
                "Hugging Face's rate limit has been reached for now."
                + (f" Try again in about {retry_after}s." if retry_after else "")
            ) from exc
        raise RerankError(f"Hugging Face rerank request failed: {exc}") from exc
    except httpx.HTTPError as exc:
        raise RerankError(f"Hugging Face rerank request failed: {exc}") from exc

    # The router batches same-shape pair inputs into one inner list, in the
    # order given: [[{"label": ..., "score": s0}, {"label": ..., "score": s1}, ...]]
    try:
        scores = [item["score"] for item in data[0]]
    except (KeyError, IndexError, TypeError) as exc:
        raise RerankError(f"Unexpected rerank response shape: {data!r}") from exc

    if len(scores) != len(candidates):
        raise RerankError(
            f"Rerank returned {len(scores)} scores for {len(candidates)} candidates."
        )

    scored = [
        {**candidate, "rerank_score": score}
        for candidate, score in zip(candidates, scores)
    ]
    scored.sort(key=lambda c: c["rerank_score"], reverse=True)
    return scored[:top_n]


def retrieve(
    query: str,
    top_k: int = 10,
    candidate_pool: int = RERANK_CANDIDATE_POOL,
    jurisdiction: str | None = None,
) -> list[dict]:
    """Hybrid search, then rerank the pool down to top_k. Main entry point."""
    candidates = hybrid_search(query, top_k=candidate_pool, jurisdiction=jurisdiction)
    return rerank(query, candidates, top_n=top_k)
