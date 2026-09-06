"""
External (AS/NZS) standard references.

Still always bare inline text -- never wrapped in an `<a>` (verified: zero
`<a>`-wrapped "AS ..." mentions in the v1.2 corpus, same as before). Must be
regex-extracted from chunk text, then normalized against every
"Schedule of referenced documents" table-reference in the corpus (it recurs
per-Part now -- 11 occurrences in Volume Two, 8 in Housing Provisions --
rather than one master file like the old export).
"""

import re

_MENTION_RE = re.compile(
    r"\bAS(?:/NZS)?\s*\d{2,5}(?:\.\d+)*(?:\s*Part\s*\d+)?\b", re.IGNORECASE
)
_WHITESPACE_RE = re.compile(r"\s+")


def extract_standard_mentions(text: str) -> list:
    seen = []
    for m in _MENTION_RE.finditer(text):
        mention = _WHITESPACE_RE.sub(" ", m.group(0)).strip()
        if mention not in seen:
            seen.append(mention)
    return seen


def normalize_standard_number(number: str) -> str:
    n = number.upper()
    n = re.sub(r"\bPART\s*(\d+)", r".\1", n)
    n = re.sub(r"\s*/\s*", "/", n)
    n = _WHITESPACE_RE.sub(" ", n).strip()
    return n


def _row_text(cell) -> str:
    return "".join(cell.itertext()).strip()


def build_standards_lookup(root) -> dict:
    """Scan every "Schedule of referenced documents" table-reference in `root`
    and merge their rows into normalize_standard_number(number) -> {..}."""
    lookup = {}
    for table_ref in root.iter("table-reference"):
        title = table_ref.findtext("title") or ""
        if "schedule of referenced documents" not in title.lower():
            continue
        table = table_ref.find("table")
        if table is None:
            continue
        tbody = table.find("tbody")
        if tbody is None:
            continue
        for tr in tbody.findall("tr"):
            cells = tr.findall("td")
            if len(cells) < 3:
                continue
            number = _row_text(cells[0])
            date = _row_text(cells[1])
            title_text = _row_text(cells[2])
            if not number:
                continue
            lookup[normalize_standard_number(number)] = {
                "standard": number,
                "date": date or None,
                "title": title_text or None,
            }
    return lookup
