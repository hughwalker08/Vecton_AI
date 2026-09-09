"""Glossary entries: `<glossentry category=.. id="_GUID"><glossterm/><glossdef><content>...</content></glossdef></glossentry>`."""

from app.ingest.chunker import render_content
from app.ingest.hierarchy import ancestor_path
from app.ingest.records import ChunkRecord


def glossary_term(glossentry_el) -> str:
    return glossentry_el.findtext("glossterm")


def parse_glossary_file(glossentry_el, corpus) -> ChunkRecord:
    term = glossary_term(glossentry_el)
    content = glossentry_el.find("glossdef/content")
    definition = render_content(content) if content is not None else ""
    return ChunkRecord(
        id=glossentry_el.get("id", "").removeprefix("_"),
        node_type="glossary",
        hierarchy=ancestor_path(corpus.doc_label, glossentry_el),
        heading=term,
        doc=corpus.doc_label,
        text=definition,
    )
