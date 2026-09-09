"""
Standalone figure rows: `<image-reference id=.. num=..><title/><img src="file.svg"/></image-reference>`.

No more GUID-stub indirection -- `src` is a direct, working filename against
the sibling `images/` folder.
"""

from app.ingest.hierarchy import ancestor_path
from app.ingest.records import ChunkRecord


def parse_figure_file(image_ref_el, corpus):
    num = image_ref_el.get("num")
    title = image_ref_el.findtext("title")
    heading = f"Figure {num}: {title}" if num and title else (title or (f"Figure {num}" if num else None))

    img = image_ref_el.find("img")
    src = img.get("src") if img is not None else None
    matched = bool(src) and (corpus.images_dir / src).exists()

    image_refs = []
    if matched:
        image_refs.append(
            {
                "image_id": image_ref_el.get("id", "").removeprefix("_"),
                "filename": src,
                "caption": heading,
            }
        )

    chunk = ChunkRecord(
        id=image_ref_el.get("id", "").removeprefix("_"),
        node_type="figure",
        hierarchy=ancestor_path(corpus.doc_label, image_ref_el),
        heading=heading,
        doc=corpus.doc_label,
        text=title or "",
        image_refs=image_refs,
    )
    return chunk, (src if matched else None)
