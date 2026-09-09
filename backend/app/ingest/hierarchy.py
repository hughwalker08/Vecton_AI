"""
Hierarchy: a direct ancestor walk.

The v1.2 schema is a real nested tree (ncc-section -> part/specification ->
subtopic -> clause -> subclause), so every clause's position is just read
off `element.iterancestors()` -- no more layered GUID-stub resolution, no
fallback tier, and no "orphan clauses" (every clause in the new, properly
NCC-Volume-Two-scoped corpus is genuinely nested somewhere).
"""


def ancestor_path(doc_label: str, element) -> list:
    path = [doc_label]
    for anc in reversed(list(element.iterancestors())):
        if anc.tag == "ncc-section":
            num = anc.get("num")
            title = anc.findtext("title")
            label = " ".join(x for x in (num, title) if x)
            if label:
                path.append(label)
        elif anc.tag in ("part", "specification"):
            num = anc.get("num")
            title = anc.findtext("title")
            label = " ".join(x for x in (num, title) if x)
            if label:
                path.append(label)
    return path
