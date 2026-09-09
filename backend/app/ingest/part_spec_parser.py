"""Standalone `part`/`specification` rows: `num` attribute + `<title>` (+ `<intro-part><content>` prose for parts)."""

from app.ingest.applicability import extract_jurisdiction
from app.ingest.chunker import render_content
from app.ingest.hierarchy import ancestor_path
from app.ingest.records import ChunkRecord


def parse_part_or_spec(el, corpus) -> ChunkRecord:
    num = el.get("num")
    title = el.findtext("title")
    node_type = "specification" if el.tag == "specification" else "part"
    heading = " ".join(x for x in (num, title) if x) or None

    intro_content = el.find("intro-part/content")
    text = render_content(intro_content) if intro_content is not None else (title or "")

    return ChunkRecord(
        id=el.get("id", "").removeprefix("_"),
        node_type=node_type,
        clause_id=num,
        hierarchy=ancestor_path(corpus.doc_label, el),
        heading=heading,
        doc=corpus.doc_label,
        text=text,
        jurisdictions=extract_jurisdiction(el),
    )


def parse_part_variation(el, corpus) -> ChunkRecord:
    """`<part-variation type="DELETE"|"REPLACE" state=.. num=..>` -- a
    jurisdiction-specific note about a whole Part (e.g. "this Part does not
    apply in Tasmania"). Not a full part, but informative enough to chunk."""
    num = el.get("num")
    state = el.get("state")
    variation_type = el.get("type")
    content = el.find("content")
    text = render_content(content) if content is not None else ""
    heading = f"Part {num} variation ({state})" if num else f"Part variation ({state})"

    return ChunkRecord(
        id=el.get("id", "").removeprefix("_"),
        node_type="note",
        clause_id=num,
        hierarchy=ancestor_path(corpus.doc_label, el),
        heading=heading,
        doc=corpus.doc_label,
        text=text,
        jurisdictions=[state] if state else None,
        applicability_note=variation_type,
    )
