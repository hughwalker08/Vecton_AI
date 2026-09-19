"""
Pull embedded images out of a user-uploaded document, and describe them.

Part B of the plan (user document uploads) treats an upload the same way the
NCC/ABCB corpus is treated: text gets chunked and embedded, and figures get
transcribed so their content is searchable. A submitted set of house plans
carries most of its compliance detail in the drawings, so an upload pipeline
that only reads the prose misses the part that matters.

    extract_images()   -- DOCX (stdlib zipfile) and PDF (PyMuPDF) -> bytes
    describe_document_images()  -- run those through the vision service

Text extraction is NOT here: DOCX goes through python-docx and PDF through
LlamaParse (settings.PDF_PARSER), neither of which is wired up yet. This
module is only the image half, and is independent of it.
"""

from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from app.services.document_captions import (
    Caption,
    best_caption,
    from_alt_text,
    from_nearby_text,
    from_paragraph,
)
from app.services.image_description import (
    ImageDescriptionError,
    build_model,
    describe_image_bytes,
)

DOCX_EXTENSIONS = {".docx"}
PDF_EXTENSIONS = {".pdf"}
SUPPORTED_DOCUMENTS = DOCX_EXTENSIONS | PDF_EXTENSIONS

# Decorative images -- letterhead logos, bullet glyphs, signature strips,
# rule lines -- carry no compliance content but would each cost an API call.
# Anything below both floors is skipped. These are deliberately generous:
# a genuine detail drawing comfortably clears them, and the cost of skipping
# a real figure is much higher than the cost of describing a logo.
# OOXML namespaces. `w` is WordprocessingML (paragraphs, runs, styles),
# `a` DrawingML (the blip that names the image part), `r` relationships, and
# `wp` the drawing wrapper that carries alt text.
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"

MIN_IMAGE_BYTES = 8 * 1024
MIN_IMAGE_PIXELS = 200  # on the shorter side, where dimensions are readable


@dataclass
class ExtractedImage:
    """One image lifted out of an uploaded document."""

    name: str  # synthetic, stable within the document, e.g. "page3_img1.png"
    data: bytes
    source: str  # where it came from: "word/media/image3.png" or "page 3"
    width: int | None = None
    height: int | None = None
    # What the document called this drawing, when it could be found. Carried
    # into the transcription prompt and back out on the finding, so a
    # description stays attached to the figure it belongs to.
    caption: Caption | None = None

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()

    @property
    def caption_text(self) -> str | None:
        return self.caption.text if self.caption else None


@dataclass
class ImageFinding:
    """The result of describing one extracted image."""

    name: str
    source: str
    description: str | None = None
    error: str | None = None
    width: int | None = None
    height: int | None = None
    caption: str | None = None
    # How the caption was found -- "alt-text", "caption-style",
    # "caption-pattern" or "nearby-text". A reviewer weighing a finding needs
    # to know whether the caption was authored or inferred from proximity.
    caption_source: str | None = None

    @property
    def ok(self) -> bool:
        return self.description is not None


@dataclass
class DocumentImageReport:
    filename: str
    images_found: int = 0
    images_skipped: int = 0  # below the decorative-image floors
    described: int = 0
    failed: int = 0
    captioned: int = 0  # images matched to a caption in the document
    findings: list = field(default_factory=list)


class DocumentImageError(RuntimeError):
    """Raised when a document's images cannot be extracted."""


# --------------------------------------------------------------------------
# Dimension sniffing (stdlib only)
# --------------------------------------------------------------------------

def image_size(data: bytes) -> tuple[int | None, int | None]:
    """Read (width, height) from PNG/JPEG/GIF headers without decoding.

    Used to filter decorative images out of a DOCX, where -- unlike PDF --
    the container gives us no dimensions. Returns (None, None) for anything
    it doesn't recognise, which the caller treats as "unknown, keep it".
    """
    if len(data) < 24:
        return None, None

    # PNG: 8-byte signature, then IHDR with width/height as big-endian uint32.
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        return width, height

    # GIF: little-endian uint16 pair at offset 6.
    if data[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", data[6:10])
        return width, height

    # JPEG: walk the marker segments to the start-of-frame.
    if data[:2] == b"\xff\xd8":
        i = 2
        end = len(data)
        while i + 9 < end:
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            # SOF0-SOF15, excluding the non-frame markers DHT/JPG/DAC.
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[i + 5 : i + 9])
                return width, height
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            (segment_length,) = struct.unpack(">H", data[i + 2 : i + 4])
            i += 2 + segment_length
        return None, None

    return None, None


def is_decorative(image: ExtractedImage) -> bool:
    """True if the image looks like a logo/glyph rather than a figure."""
    if image.width and image.height:
        if min(image.width, image.height) < MIN_IMAGE_PIXELS:
            return True
    return len(image.data) < MIN_IMAGE_BYTES


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------

def _docx_relationships(archive: zipfile.ZipFile) -> dict[str, str]:
    """Map relationship id -> `word/media/...` path from the document rels part."""
    try:
        rels_xml = archive.read("word/_rels/document.xml.rels")
    except KeyError:
        return {}

    rels: dict[str, str] = {}
    for rel in ET.fromstring(rels_xml):
        rel_id, target = rel.get("Id"), rel.get("Target")
        if not rel_id or not target:
            continue
        if rel.get("TargetMode") == "External":
            continue  # linked, not embedded -- the bytes aren't in the archive
        # Targets are relative to word/, and may be written "../word/media/x".
        rels[rel_id] = "word/" + target.lstrip("/").replace("../", "")
    return rels


def _paragraph_text(paragraph) -> str:
    """Visible text of a <w:p>, concatenating its runs."""
    return "".join(node.text or "" for node in paragraph.iter(f"{{{_W_NS}}}t"))


def _paragraph_style(paragraph) -> str | None:
    """The <w:pStyle> value of a paragraph, if it sets one."""
    for style in paragraph.iter(f"{{{_W_NS}}}pStyle"):
        return style.get(f"{{{_W_NS}}}val")
    return None


def _drawings_in(paragraph) -> list[tuple[str, str | None, str | None]]:
    """(relationship id, alt-text, shape name) for each image in a paragraph."""
    found = []
    for blip in paragraph.iter(f"{{{_A_NS}}}blip"):
        rel_id = blip.get(f"{{{_R_NS}}}embed")
        if rel_id:
            found.append(rel_id)
    if not found:
        return []

    # wp:docPr carries the author's alt text (@descr) and the shape's name.
    # One docPr per drawing, in the same order as the blips.
    props = [
        (node.get("descr"), node.get("name"))
        for node in paragraph.iter(f"{{{_WP_NS}}}docPr")
    ]
    out = []
    for i, rel_id in enumerate(found):
        descr, name = props[i] if i < len(props) else (None, None)
        out.append((rel_id, descr, name))
    return out


def extract_from_docx(data: bytes) -> list[ExtractedImage]:
    """Pull images out of a DOCX, in document order, with their captions.

    A DOCX is a zip, so this needs no third-party library -- but reading
    `word/media/*` directly would throw away the one thing captions depend on:
    where each image sits in the document. So this walks `word/document.xml`
    in order instead, resolving each drawing's relationship id to its media
    part, and looks at the paragraphs on either side for a caption.

    Images referenced more than once are extracted once, under the first
    caption found for them.
    """
    images: list[ExtractedImage] = []
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            rels = _docx_relationships(archive)
            try:
                document_xml = archive.read("word/document.xml")
            except KeyError as exc:
                raise DocumentImageError("not a readable DOCX (no word/document.xml)") from exc

            body = ET.fromstring(document_xml)
            paragraphs = list(body.iter(f"{{{_W_NS}}}p"))

            # Pre-compute text and style once; the caption search reads
            # neighbours repeatedly.
            texts = [_paragraph_text(p) for p in paragraphs]
            styles = [_paragraph_style(p) for p in paragraphs]

            seen_targets: set[str] = set()
            for index, paragraph in enumerate(paragraphs):
                for rel_id, alt, shape_name in _drawings_in(paragraph):
                    target = rels.get(rel_id)
                    if not target or target in seen_targets:
                        continue
                    try:
                        blob = archive.read(target)
                    except KeyError:
                        continue  # dangling relationship
                    if not blob:
                        continue
                    seen_targets.add(target)

                    caption = _docx_caption(index, texts, styles, alt, shape_name)
                    width, height = image_size(blob)
                    suffix = Path(target).suffix.lower() or ".png"
                    images.append(
                        ExtractedImage(
                            name=f"img{len(images) + 1}{suffix}",
                            data=blob,
                            source=target,
                            width=width,
                            height=height,
                            caption=caption,
                        )
                    )

            # Anything embedded but never referenced from the body (headers,
            # footers, textboxes) is still worth transcribing -- just without
            # a caption, since there is no document position to search around.
            for entry in sorted(archive.namelist()):
                if not entry.startswith("word/media/") or entry in seen_targets:
                    continue
                blob = archive.read(entry)
                if not blob:
                    continue
                width, height = image_size(blob)
                suffix = Path(entry).suffix.lower() or ".png"
                images.append(
                    ExtractedImage(
                        name=f"img{len(images) + 1}{suffix}",
                        data=blob,
                        source=entry,
                        width=width,
                        height=height,
                    )
                )
    except zipfile.BadZipFile as exc:
        raise DocumentImageError("not a readable DOCX (bad zip archive)") from exc
    except ET.ParseError as exc:
        raise DocumentImageError(f"not a readable DOCX (malformed XML: {exc})") from exc
    return images


def _docx_caption(index, texts, styles, alt, shape_name) -> Caption | None:
    """Best caption for an image in paragraph `index`.

    Alt text wins when the author wrote any, because it describes that exact
    drawing. Otherwise look at the paragraph the image sits in (Word puts a
    caption in the same paragraph often enough), then the one after -- the
    conventional place for a figure caption -- then the one before.
    """
    candidates: list[Caption] = []

    authored = from_alt_text(alt, shape_name)
    if authored:
        candidates.append(authored)

    # Own paragraph first: an inline image followed by its label on the same
    # line. Then below, then above.
    for offset in (0, 1, -1):
        neighbour = index + offset
        if not 0 <= neighbour < len(texts):
            continue
        text = texts[neighbour]
        if offset == 0 and not text.strip():
            continue
        found = from_paragraph(text, styles[neighbour])
        if found:
            # A caption directly below the image is the convention; nudge the
            # others down so a styled caption below beats a pattern match above.
            if offset == -1:
                found.confidence -= 0.05
            candidates.append(found)

    return best_caption(candidates)


def _import_pymupdf():
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        try:
            import fitz  # older PyMuPDF releases

            return fitz
        except ImportError as exc:
            raise DocumentImageError(
                "PDF image extraction needs PyMuPDF. Run: pip install pymupdf"
            ) from exc


# How far below an image to keep looking for its caption, in points (72/inch).
# Much beyond this and the text belongs to the next paragraph, not the figure.
CAPTION_SEARCH_BELOW = 140
# Above the image, only a caption-shaped line counts, so the window can be
# tighter -- it exists for the layouts that print the label over the figure.
CAPTION_SEARCH_ABOVE = 80
# Fraction of the image's width a text block must span to be considered its
# caption, rather than a neighbouring column.
MIN_HORIZONTAL_OVERLAP = 0.25


def _horizontal_overlap(image_rect, block_rect) -> float:
    """Overlap of a text block with an image's x-range, as a 0-1 fraction."""
    left = max(image_rect[0], block_rect[0])
    right = min(image_rect[2], block_rect[2])
    if right <= left:
        return 0.0
    image_width = image_rect[2] - image_rect[0]
    return (right - left) / image_width if image_width > 0 else 0.0


def _pdf_caption(image_rect, blocks) -> Caption | None:
    """Best caption for an image at `image_rect` from a page's text blocks.

    `blocks` is PyMuPDF's `page.get_text("blocks")`: tuples of
    (x0, y0, x1, y1, text, block_no, block_type). Only text blocks (type 0)
    are considered.
    """
    candidates: list[Caption] = []

    for block in blocks:
        if len(block) < 5:
            continue
        # block_type 1 is an image block, not text.
        if len(block) >= 7 and block[6] != 0:
            continue
        x0, y0, x1, y1, text = block[0], block[1], block[2], block[3], block[4]
        if not str(text).strip():
            continue
        if _horizontal_overlap(image_rect, (x0, y0, x1, y1)) < MIN_HORIZONTAL_OVERLAP:
            continue

        # PDF user space here has y increasing downwards (PyMuPDF normalises
        # to that), so "below the image" means a larger y.
        if y0 >= image_rect[3]:
            distance = y0 - image_rect[3]
            if distance > CAPTION_SEARCH_BELOW:
                continue
            found = from_nearby_text(str(text), distance, below=True)
        elif y1 <= image_rect[1]:
            distance = image_rect[1] - y1
            if distance > CAPTION_SEARCH_ABOVE:
                continue
            found = from_nearby_text(str(text), distance, below=False)
        else:
            continue  # overlaps the image itself -- that's a label, not a caption

        if found:
            candidates.append(found)

    return best_caption(candidates)


def extract_from_pdf(data: bytes) -> list[ExtractedImage]:
    """Pull embedded raster images out of a PDF, with their captions.

    De-duplicated by xref, so a logo repeated on forty pages costs one
    description rather than forty. The caption search uses the image's
    placement on the page it first appears on: a PDF has no document order,
    only coordinates, so "the caption" is whatever text sits closest under
    the image's bounding box (see document_captions._pdf rules).
    """
    pymupdf = _import_pymupdf()

    images: list[ExtractedImage] = []
    seen_xrefs: set[int] = set()
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            for page_number in range(doc.page_count):
                page = doc[page_number]
                blocks = None  # computed lazily; most pages have no new images

                for entry in doc.get_page_images(page_number, full=True):
                    xref = entry[0]
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    try:
                        extracted = doc.extract_image(xref)
                    except Exception:  # noqa: BLE001 - damaged/unsupported object
                        continue
                    blob = extracted.get("image")
                    if not blob:
                        continue

                    caption = None
                    try:
                        rects = page.get_image_rects(xref)
                    except Exception:  # noqa: BLE001 - older PyMuPDF, odd placement
                        rects = []
                    if rects:
                        if blocks is None:
                            blocks = page.get_text("blocks")
                        rect = rects[0]
                        caption = _pdf_caption(
                            (rect.x0, rect.y0, rect.x1, rect.y1), blocks
                        )

                    suffix = f".{extracted.get('ext', 'png')}"
                    images.append(
                        ExtractedImage(
                            name=f"page{page_number + 1}_img{len(images) + 1}{suffix}",
                            data=blob,
                            source=f"page {page_number + 1}",
                            width=extracted.get("width"),
                            height=extracted.get("height"),
                            caption=caption,
                        )
                    )
    except DocumentImageError:
        raise
    except Exception as exc:  # noqa: BLE001 - encrypted, truncated, not a PDF
        raise DocumentImageError(f"could not read PDF: {exc}") from exc
    return images


def extract_images(data: bytes, filename: str) -> list[ExtractedImage]:
    """Extract embedded images from an uploaded DOCX or PDF."""
    suffix = Path(filename).suffix.lower()
    if suffix in DOCX_EXTENSIONS:
        return extract_from_docx(data)
    if suffix in PDF_EXTENSIONS:
        return extract_from_pdf(data)
    raise DocumentImageError(
        f"unsupported document type '{suffix or filename}' -- "
        f"expected one of {', '.join(sorted(SUPPORTED_DOCUMENTS))}"
    )


# --------------------------------------------------------------------------
# Extract + describe
# --------------------------------------------------------------------------

def describe_document_images(
    data: bytes,
    filename: str,
    model=None,
    max_images: int | None = None,
    skip_decorative: bool = True,
) -> DocumentImageReport:
    """Extract every image from an uploaded document and describe each one.

    One failure does not sink the upload: a per-image error is recorded on
    that finding and the rest continue, so a single unreadable drawing
    doesn't cost the user the other forty.
    """
    report = DocumentImageReport(filename=filename)

    images = extract_images(data, filename)
    report.images_found = len(images)

    if skip_decorative:
        kept = [img for img in images if not is_decorative(img)]
        report.images_skipped = len(images) - len(kept)
        images = kept

    if max_images is not None:
        images = images[:max_images]

    if not images:
        return report

    # Build the model once for the whole document, not once per image.
    handle = model if model is not None else build_model()

    for image in images:
        finding = ImageFinding(
            name=image.name,
            source=image.source,
            width=image.width,
            height=image.height,
            caption=image.caption_text,
            caption_source=image.caption.source if image.caption else None,
        )
        if finding.caption:
            report.captioned += 1
        try:
            result = describe_image_bytes(
                image.data, image.name, model=handle, caption=image.caption_text
            )
            finding.description = result.text
            report.described += 1
        except ImageDescriptionError as exc:
            finding.error = str(exc)
            report.failed += 1
        except Exception as exc:  # noqa: BLE001 - provider/transport faults
            finding.error = f"{type(exc).__name__}: {exc}"
            report.failed += 1
        report.findings.append(finding)

    return report
