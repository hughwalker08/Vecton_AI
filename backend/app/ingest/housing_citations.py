"""
Fix for the reported bug: NCC clause text cites the ABCB Housing Provisions
in bare prose with NO `<a>` tag at all -- e.g. "...in accordance with
Section 4 of the ABCB Housing Provisions." or "Compliance with WA Part 9.6
of the ABCB Housing Provisions satisfies...". Confirmed by direct inspection
that this coexists, inconsistently, with properly-linked citations of the
same fact elsewhere in the same corpus -- so it can't be fixed by just using
`<a>` tags better; these mentions need their own regex extraction, parallel
to how AS/NZS standard mentions are extracted (see standards.py).

Once extracted, the citation's Part/Section/Clause/Table/Figure number is
text-matched against the Housing Provisions corpus's own numbering (`<part
num=..>`, `<clause><sptc>..</sptc></clause>`, `<table-reference num=..>`,
`<image-reference num=..>`) to recover the target element's GUID, which the
shared post-pass (resolve_internal_refs.py) then resolves to a real chunk_id
exactly like any other cross-corpus reference.
"""

import re

_CITATION_RE = re.compile(
    r"\b(?:[A-Z]{2,3}\s+)?(Part|Section|Clause|Table|Figure)\s+"
    r"(\d+(?:\.\d+)*)((?:\([a-zA-Z0-9]+\))*)"
    r"\s+of the (?:ABCB )?Housing Provisions",
    re.IGNORECASE,
)

_LABEL_TO_INDEX_KEY = {
    "part": "part",
    "clause": "clause",
    "table": "table",
    "figure": "figure",
    # "section" deliberately excluded: a Section is a broad grouping (and its
    # numbering isn't even unique -- e.g. num="4" is both "Footings and slabs"
    # and, in the state-schedule appendix, "Australian Capital Territory"), so
    # it never points at one specific piece of content. Citations naming a
    # bare Section number are still captured, just left unresolved.
}


def _index_by_attr(root, tag: str, key: str) -> dict:
    """number -> element, but only where the number is unique for `tag` --
    a duplicate (confirmed to occur for some Part/Table/Figure numbers,
    reused between the national provisions and the state-schedule appendix)
    is left out entirely rather than risk silently resolving to the wrong one."""
    seen = {}
    ambiguous = set()
    for el in root.iter(tag):
        num = el.get(key) if key != "sptc" else el.findtext("sptc")
        if not num:
            continue
        num = num.strip()
        if num in seen and seen[num] is not el:
            ambiguous.add(num)
        else:
            seen[num] = el
    for num in ambiguous:
        seen.pop(num, None)
    return seen


def build_number_index(housing_root) -> dict:
    """label -> {number_string: element}, built once from the Housing Provisions corpus."""
    return {
        "part": _index_by_attr(housing_root, "part", "num"),
        "clause": _index_by_attr(housing_root, "clause", "sptc"),
        "table": _index_by_attr(housing_root, "table-reference", "num"),
        "figure": _index_by_attr(housing_root, "image-reference", "num"),
    }


def extract_bare_housing_citations(text: str, number_index: dict) -> list:
    """Returns external_refs-shaped dicts (with a private `_target_guid` the
    shared post-pass resolves to `chunk_id`, then strips)."""
    results = []
    seen = set()
    for m in _CITATION_RE.finditer(text):
        label = m.group(1).lower()
        number = m.group(2)
        suffix = m.group(3) or ""
        raw_text = m.group(0)
        display = f"{m.group(1).capitalize()} {number}{suffix}"
        if display in seen:
            continue
        seen.add(display)

        target_el = number_index.get(_LABEL_TO_INDEX_KEY.get(label, ""), {}).get(number)
        results.append(
            {
                "kind": "housing",
                "clause_id": display,
                "raw_text": raw_text,
                "chunk_id": None,
                "_target_guid": target_el.get("id") if target_el is not None else None,
                "_target_corpus": "housing",
            }
        )
    return results
