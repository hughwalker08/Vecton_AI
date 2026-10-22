"""Glossary entries: `<glossentry category=.. id="_GUID">
<glossterm/><glossdef><content>...</content></glossdef></glossentry>`."""

from app.ingest.chunker import render_content
from app.ingest.hierarchy import ancestor_path
from app.ingest.records import ChunkRecord


def glossary_term(glossentry_el) -> str:
    return glossentry_el.findtext("glossterm")


def parse_glossary_file(glossentry_el, corpus) -> ChunkRecord:
    term = glossary_term(glossentry_el)
    # A definition with a list ("habitable room ... and— (a) includes ...") is
    # split across several <content> blocks: the lead-in, then the list.
    # Reading only the first dropped the list from 73 of 493 entries.
    blocks = [render_content(content) for content in glossentry_el.findall("glossdef/content")]
    definition = "\n".join(block for block in blocks if block)
    return ChunkRecord(
        id=glossentry_el.get("id", "").removeprefix("_"),
        node_type="glossary",
        hierarchy=ancestor_path(corpus.doc_label, glossentry_el),
        heading=term,
        doc=corpus.doc_label,
        text=definition,
    )
