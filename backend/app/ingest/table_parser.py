"""
Standalone table rows: `<table-reference id=.. num=.. sptc=..><title/><table>
<thead>/<tbody> real HTML-like rows</table></table-reference>`.

Unlike the old export (caption-only stub), real cell content is now
available cheaply -- render it, it's much more useful for retrieval.
"""

from app.ingest.hierarchy import ancestor_path
from app.ingest.records import ChunkRecord


def _cell_text(cell) -> str:
    return " ".join("".join(cell.itertext()).split())


def _render_table(table_el) -> str:
    lines = []
    for section_tag in ("thead", "tbody"):
        section = table_el.find(section_tag)
        if section is None:
            continue
        for tr in section.findall("tr"):
            cells = tr.findall("th") + tr.findall("td")
            row_text = " | ".join(_cell_text(c) for c in cells if _cell_text(c))
            if row_text:
                lines.append(row_text)
    return "\n".join(lines)


def parse_table_file(table_ref_el, corpus) -> ChunkRecord:
    num = table_ref_el.get("num")
    title = table_ref_el.findtext("title")
    heading = f"Table {num}: {title}" if num and title else (title or (f"Table {num}" if num else None))

    table_el = table_ref_el.find("table")
    body_text = _render_table(table_el) if table_el is not None else ""
    text = f"{title}\n{body_text}" if title and body_text else (body_text or title or "")

    return ChunkRecord(
        id=table_ref_el.get("id", "").removeprefix("_"),
        node_type="table",
        clause_id=table_ref_el.get("sptc") or None,
        hierarchy=ancestor_path(corpus.doc_label, table_ref_el),
        heading=heading,
        doc=corpus.doc_label,
        text=text,
    )
