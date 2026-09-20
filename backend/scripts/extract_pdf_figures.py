#!/usr/bin/env python3
"""
Extract the figures from the NCC 2025 / ABCB Housing Provisions PDFs as PNGs.

The figures in these documents are **vector artwork**, not embedded images:
across both PDFs there are 8 embedded image objects but 269 captioned figures,
and thousands of vector draw operations. So `get_page_images()` finds almost
nothing, and the figure has to be rendered from the page instead.

The approach:

  1. Find every caption block -- "Figure 10.2.15a: ..." or
     "Figure H1D4a (explanatory): ..." -- using the shared caption pattern.
  2. Take the vector drawings sitting BELOW that caption, down to the next
     caption on the page. These documents print the caption above its figure,
     not under it -- measured across both PDFs, "artwork below the caption"
     locates 279 of 280 figures, where "above" finds barely half.
  3. Pull in text blocks in the same band: the figure's own labels and
     dimension callouts are separate objects, and clipping them would lose
     exactly the numbers that matter most.
  4. Render that region to PNG at `--zoom` scale, caption included, so each
     image is self-contained.

Output is a folder of PNGs plus `captions.json`, ready for:

    python scripts/describe_images.py data/images/vol2 \\
        --captions data/images/vol2/captions.json \\
        --out app/ingest/output/vol2_image_descriptions.jsonl

Usage:
    python scripts/extract_pdf_figures.py \\
        --pdf "data/source/NCC 2025 Volume Two.pdf" --corpus vol2
    python scripts/extract_pdf_figures.py --all      # both, using the defaults
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.document_captions import CAPTION_PATTERN, clean  # noqa: E402

DEFAULT_SOURCES = {
    "vol2": BACKEND_DIR / "data" / "source" / "NCC 2025 Volume Two.pdf",
    "housing": BACKEND_DIR / "data" / "source" / "NCC 2025 Housing Provisions.pdf",
}
DEFAULT_OUT = BACKEND_DIR / "data" / "images"

# Only figures -- "Table 7.2" captions in these documents label real tables,
# which the ingest pipeline already parses as text far more accurately than a
# vision model could read them off a rendered page.
FIGURE_KINDS = {"figure", "fig", "fig."}

# Page furniture: both documents draw a header rule at y=50 and a footer rule
# at y=814 on every page. Including them would stretch every figure to the
# full page height.
MARGIN_TOP = 55
MARGIN_BOTTOM = 810
# Ignore hairline artefacts when deciding what the figure is.
MIN_DRAWING_SIDE = 3
# Padding around the union, so nothing is clipped at the edge.
PAD = 8
# A region smaller than this is almost certainly a stray rule, not a figure.
MIN_REGION_HEIGHT = 40
MIN_REGION_WIDTH = 80


def import_pymupdf():
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        try:
            import fitz

            return fitz
        except ImportError:
            print("PyMuPDF is required. Run: pip install pymupdf", file=sys.stderr)
            raise SystemExit(2) from None


def caption_parts(text: str) -> tuple[str, str] | None:
    """(figure number, full caption line) if `text` opens a figure caption."""
    text = clean(text)
    if not text:
        return None
    match = CAPTION_PATTERN.match(text)
    if not match:
        return None
    kind = (match.group("kind") or "").lower().rstrip(".")
    if kind not in {k.rstrip(".") for k in FIGURE_KINDS}:
        return None
    number = match.group("number")
    if not number:
        return None
    # A cross-reference in prose ("See Figure H1D4a.") is not a caption: a real
    # caption block starts with the word Figure and carries its own title.
    if not (match.group("sep") or match.group("qualifier")):
        return None
    return number, text


def safe_name(number: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", number)


def figure_region(page, caption_rect, next_caption_top, drawings, blocks, pymupdf):
    """Bounding box of the figure belonging to the caption at `caption_rect`.

    These documents print the caption *above* its artwork, so the figure is
    whatever is drawn between this caption and the next one on the page. The
    caption itself is included, so the rendered image carries its own title.
    """
    lower_bound = min(next_caption_top, MARGIN_BOTTOM)
    region = None

    for drawing in drawings:
        rect = drawing.get("rect")
        if rect is None:
            continue
        if rect.width < MIN_DRAWING_SIDE and rect.height < MIN_DRAWING_SIDE:
            continue
        if rect.y0 < caption_rect.y1 - 2 or rect.y1 > lower_bound:
            continue
        if rect.y0 < MARGIN_TOP:
            continue
        region = rect if region is None else region | rect

    if region is None:
        return None

    # Figure labels and dimension callouts are separate text objects sitting
    # over the artwork; losing them would lose the numbers.
    for block in blocks:
        rect = pymupdf.Rect(block[0], block[1], block[2], block[3])
        if rect.y0 < caption_rect.y1 - 2 or rect.y1 > lower_bound:
            continue
        if rect.x1 < region.x0 - 40 or rect.x0 > region.x1 + 40:
            continue
        region = region | rect

    # Include the caption line itself so the image is self-contained.
    region = region | caption_rect

    region = pymupdf.Rect(
        max(region.x0 - PAD, page.rect.x0),
        max(region.y0 - PAD, page.rect.y0),
        min(region.x1 + PAD, page.rect.x1),
        min(region.y1 + PAD, page.rect.y1),
    )
    if region.height < MIN_REGION_HEIGHT or region.width < MIN_REGION_WIDTH:
        return None
    return region


def extract(pdf_path: Path, corpus: str, out_dir: Path, zoom: float, limit: int | None):
    pymupdf = import_pymupdf()

    corpus_dir = out_dir / corpus
    corpus_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    captions: dict[str, str] = {}
    written = 0
    skipped_no_region = []
    seen_numbers: set[str] = set()

    print(f"\n{corpus}: {pdf_path.name} ({doc.page_count} pages)")

    for page_number in range(doc.page_count):
        page = doc[page_number]
        blocks = page.get_text("blocks")
        found = [
            (parts, pymupdf.Rect(b[0], b[1], b[2], b[3]))
            for b in blocks
            for parts in [caption_parts(b[4] or "")]
            if parts
        ]
        if not found:
            continue

        found.sort(key=lambda item: item[1].y0)
        drawings = page.get_drawings()
        for index, ((number, caption_text), caption_rect) in enumerate(found):
            if number in seen_numbers:
                continue  # first occurrence wins; later ones are re-prints
            next_top = found[index + 1][1].y0 - 4 if index + 1 < len(found) else MARGIN_BOTTOM
            region = figure_region(page, caption_rect, next_top, drawings, blocks, pymupdf)
            if region is None:
                skipped_no_region.append((number, page_number + 1))
                continue

            seen_numbers.add(number)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=region)
            name = f"figure-{safe_name(number)}.png"
            (corpus_dir / name).write_bytes(pixmap.tobytes("png"))
            captions[name] = caption_text
            written += 1
            if written <= 3 or written % 25 == 0:
                print(f"  [{written}] p{page_number + 1} {name}  {caption_text[:62]}")
            if limit and written >= limit:
                break
        if limit and written >= limit:
            break

    doc.close()

    captions_path = corpus_dir / "captions.json"
    captions_path.write_text(json.dumps(captions, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"  wrote {written} figure(s) to {corpus_dir}")
    print(f"  captions -> {captions_path}")
    if skipped_no_region:
        print(f"  {len(skipped_no_region)} caption(s) had no artwork below them (likely "
              f"a figure continued from the previous page):")
        for number, page_no in skipped_no_region[:8]:
            print(f"      Figure {number} (p{page_no})")
    return written, len(skipped_no_region)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pdf", type=Path, help="source PDF")
    parser.add_argument("--corpus", choices=sorted(DEFAULT_SOURCES), help="which corpus the PDF is")
    parser.add_argument("--all", action="store_true", help="process both default PDFs")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output root (default: {DEFAULT_OUT})")
    parser.add_argument("--zoom", type=float, default=3.0,
                        help="render scale; 3.0 makes a 200pt-wide figure ~600px (default: 3.0)")
    parser.add_argument("--limit", type=int, default=None, help="stop after N figures (trial runs)")
    args = parser.parse_args(argv)

    if args.all:
        jobs = [(path, corpus) for corpus, path in sorted(DEFAULT_SOURCES.items())]
    elif args.pdf and args.corpus:
        jobs = [(args.pdf, args.corpus)]
    else:
        parser.error("give --pdf and --corpus, or --all")

    missing = [p for p, _ in jobs if not p.exists()]
    if missing:
        for path in missing:
            print(f"Not found: {path}", file=sys.stderr)
        return 1

    total = 0
    for path, corpus in jobs:
        written, _ = extract(path, corpus, args.out, args.zoom, args.limit)
        total += written

    print(f"\nDone. {total} figure(s) extracted.")
    print("Next: python scripts/describe_images.py <dir> --captions <dir>/captions.json --out <...>.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
