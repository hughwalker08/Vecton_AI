"""
GUID -> element index, built across BOTH loaded corpora.

Unlike the old schema (stale hrefs, unreliable clause/subclause GUIDs), the
v1.2 schema's `<a href="#_GUID">` links resolve reliably -- verified for
same-document links AND cross-document links between Volume Two and Housing
Provisions (8/8 tested GUIDs resolved 1:1, target's own number matching the
citation display text every time). So refs are resolved directly here at
chunk-build time; no more fuzzy text-matching fallback pass.

One known collision: shared front-matter boilerplate (e.g. the copyright
page) reuses the identical id across both corpora's `contents.xml`. Harmless
(that content is never a link target), but it means a guid can legitimately
map to entries in more than one corpus -- store a list, disambiguate at
resolution time by `publishing-id` (or by "same corpus as the link") rather
than assuming a single owner.
"""

import collections


def build_guid_index(corpora: list) -> dict:
    """dict[guid] -> list[(Corpus, element)]"""
    index = collections.defaultdict(list)
    for corpus in corpora:
        for el in corpus.root.iter():
            gid = el.get("id")
            if gid:
                index[gid].append((corpus, el))
    return index


def resolve_guid(guid: str, guid_index: dict, owning_corpus, target_publishing_id: str = None):
    """Resolve `guid` to (corpus, element).

    - If `target_publishing_id` is given (an external ref declares which
      corpus it targets), prefer a candidate from that corpus.
    - Otherwise (local ref), prefer a candidate from `owning_corpus` (the
      corpus containing the link itself).
    - Falls back to the first candidate if no preferred match is found.
    """
    candidates = guid_index.get(guid, ())
    if not candidates:
        return None
    if target_publishing_id:
        for corpus, el in candidates:
            if corpus.publishing_id == target_publishing_id:
                return corpus, el
    for corpus, el in candidates:
        if corpus is owning_corpus:
            return corpus, el
    return candidates[0]
