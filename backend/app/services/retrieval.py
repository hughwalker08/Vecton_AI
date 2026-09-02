"""
Hybrid retrieval service skeleton.

Intended approach: dense (vector) search + lexical (BM25) search, fused
with Reciprocal Rank Fusion, then reranked down to a top-N before being
sent to the LLM. Not implemented yet.
"""


def hybrid_search(query: str, top_k: int = 10) -> list[dict]:
    """Return the top_k most relevant clause chunks for the query. Not implemented yet."""
    raise NotImplementedError("Hybrid search not implemented yet.")


def rerank(query: str, candidates: list[dict], top_n: int = 10) -> list[dict]:
    """Rerank candidate chunks and keep the top_n. Not implemented yet."""
    raise NotImplementedError("Reranking not implemented yet.")
