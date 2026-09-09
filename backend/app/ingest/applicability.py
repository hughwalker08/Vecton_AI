"""
Applicability qualifiers: building class, climate zone, jurisdiction.

The v1.2 schema collapses the old repeated `<facet building="Class 1a"/>`
children into single CSV attributes directly on `<clause>`:
`building="Class 2,Class 3,..."`, `climate="Climate zone 1,Climate zone 2,..."`.
Jurisdiction is a first-class `state=""` attribute on `<subclause>` (empty =
national) rather than a filename-suffix guess.
"""

import re

_CLIMATE_ZONE_RE = re.compile(r"(\d+)")


def extract_building_classes(clause_el) -> list:
    val = clause_el.get("building")
    if not val:
        return []
    return [c.strip().removeprefix("Class ").strip() for c in val.split(",") if c.strip()]


def extract_climate_zones(clause_el) -> list:
    val = clause_el.get("climate")
    if not val:
        return []
    zones = []
    for part in val.split(","):
        m = _CLIMATE_ZONE_RE.search(part)
        if m:
            zones.append(int(m.group(1)))
    return zones


def extract_jurisdiction(element):
    """`state` attribute on a subclause/variation element -- empty/absent = national."""
    state = element.get("state")
    return [state] if state else None
