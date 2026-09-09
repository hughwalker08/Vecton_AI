"""
Final resolution pass: `_target_guid`/`_target_corpus` (set during chunk-build
by direct GUID lookup, or by the housing_citations bare-prose matcher) ->
a real `chunk_id`.

This needs to run once ALL chunks from BOTH corpora exist, because a ref's
target element is often a `<clause>` root rather than a specific subclause
(chunks are subclause-granularity) -- resolving it means mapping the clause
to a representative chunk (its first subclause, in document order), which
requires walking the corpus tree once up front (`build_element_id_to_chunk_id`)
rather than the fuzzy text-matching the old (unreliable-GUID) schema needed.
"""

_DIRECT_CHUNK_TAGS = {
    "subclause",
    "subclause-variation",
    "table-reference",
    "image-reference",
    "glossentry",
    "part",
    "specification",
    "callout",
    "part-variation",
}


def build_element_id_to_chunk_id(corpus) -> dict:
    """raw element id (with leading '_') -> chunk id (stripped) it ended up as,
    or -- for a <clause>/<clause-variation> root, which isn't itself a chunk
    -- the id of its first subclause/callout chunk."""
    mapping = {}
    for el in corpus.root.iter():
        if el.tag in _DIRECT_CHUNK_TAGS:
            gid = el.get("id")
            if gid:
                mapping[gid] = gid.removeprefix("_")

    for clause_el in corpus.root.iter():
        if clause_el.tag not in ("clause", "clause-variation"):
            continue
        gid = clause_el.get("id")
        if not gid or gid in mapping:
            continue
        first_child = next(clause_el.iter("subclause"), None)
        if first_child is None:
            first_child = next(clause_el.iter("subclause-variation"), None)
        if first_child is None:
            first_child = next(clause_el.iter("callout"), None)
        if first_child is not None and first_child.get("id"):
            mapping[gid] = first_child.get("id").removeprefix("_")

    return mapping


def resolve_refs(chunks_by_corpus: dict, element_maps: dict):
    """Mutates every chunk's internal_refs/external_refs in place, filling
    `chunk_id` and stripping the private `_target_guid`/`_target_corpus` keys
    (ChunkRecord.to_dict() also strips them defensively at serialize time).
    Returns (internal_resolved, internal_unresolved, external_refs_by_kind)."""
    internal_resolved = 0
    internal_unresolved = 0
    external_refs_by_kind = {}

    for chunks in chunks_by_corpus.values():
        for chunk in chunks:
            for ref in chunk.internal_refs:
                if _resolve_one(ref, element_maps):
                    internal_resolved += 1
                else:
                    internal_unresolved += 1

            for ref in chunk.external_refs:
                kind = ref.get("kind", "unknown")
                stats = external_refs_by_kind.setdefault(kind, {"total": 0, "resolved": 0})
                stats["total"] += 1
                if _resolve_one(ref, element_maps):
                    stats["resolved"] += 1

    return internal_resolved, internal_unresolved, external_refs_by_kind


def _resolve_one(ref: dict, element_maps: dict) -> bool:
    target_guid = ref.get("_target_guid")
    target_corpus_name = ref.get("_target_corpus")
    if target_guid and target_corpus_name in element_maps:
        chunk_id = element_maps[target_corpus_name].get(target_guid)
        if chunk_id:
            ref["chunk_id"] = chunk_id
            return True
    return ref.get("chunk_id") is not None
