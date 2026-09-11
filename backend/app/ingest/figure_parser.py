"""
Standalone figure rows: `<image-reference id=.. num=..><title/><img src="file.svg"/></image-reference>`.

No more GUID-stub indirection -- `src` is a direct, working filename against
the sibling `images/` folder.
"""

from app.ingest.hierarchy import ancestor_path
from app.ingest.image_descriptions import figure_text
from app.ingest.records import ChunkRecord


def parse_figure_file(image_ref_el, corpus, descriptions=None):
    """Build the chunk for one `<image-reference>`.

    `descriptions` is an optional DescriptionStore. When it holds a
    transcription for this figure's image, that text is folded into the
    chunk's `text` so the drawing's own dimensions and labels are embedded
    and searchable -- without it the chunk carries only the caption.
    """
    num = image_ref_el.get("num")
    title = image_ref_el.findtext("title")
    heading = f"Figure {num}: {title}" if num and title else (title or (f"Figure {num}" if num else None))

    img = image_ref_el.find("img")
    src = img.get("src") if img is not None else None
    matched = bool(src) and (corpus.images_dir / src).exists()

    description = descriptions.get(src) if (descriptions and matched) else None

    image_refs = []
    if matched:
        image_refs.append(
            {
                "image_id": image_ref_el.get("id", "").removeprefix("_"),
                "filename": src,
                "caption": heading,
                "described": description is not None,
            }
        )

    chunk = ChunkRecord(
        id=image_ref_el.get("id", "").removeprefix("_"),
        node_type="figure",
        hierarchy=ancestor_path(corpus.doc_label, image_ref_el),
        heading=heading,
        doc=corpus.doc_label,
        text=figure_text(title, description),
        image_refs=image_refs,
    )
    return chunk, (src if matched else None), (description is not None)
