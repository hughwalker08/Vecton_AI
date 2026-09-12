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
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

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

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()


@dataclass
class ImageFinding:
    """The result of describing one extracted image."""

    name: str
    source: str
    description: str | None = None
    error: str | None = None
    width: int | None = None
    height: int | None = None

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

def extract_from_docx(data: bytes) -> list[ExtractedImage]:
    """Pull `word/media/*` out of a DOCX.

    A DOCX is a zip, so this needs no third-party library. Entries are sorted
    by name, which is the order Word assigns them and therefore roughly
    document order.
    """
    images: list[ExtractedImage] = []
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = sorted(
                n for n in archive.namelist()
                if n.startswith("word/media/") and not n.endswith("/")
            )
            for i, entry in enumerate(names, 1):
                blob = archive.read(entry)
                if not blob:
                    continue
                suffix = Path(entry).suffix.lower() or ".png"
                width, height = image_size(blob)
                images.append(
                    ExtractedImage(
                        name=f"img{i}{suffix}",
                        data=blob,
                        source=entry,
                        width=width,
                        height=height,
                    )
                )
    except zipfile.BadZipFile as exc:
        raise DocumentImageError("not a readable DOCX (bad zip archive)") from exc
    return images


def extract_from_pdf(data: bytes) -> list[ExtractedImage]:
    """Pull embedded raster images out of a PDF, page by page, via PyMuPDF.

    Each image is reported once per page it appears on, but de-duplicated by
    xref so a logo repeated on forty pages costs one description, not forty.
    """
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # older PyMuPDF releases
        except ImportError as exc:
            raise DocumentImageError(
                "PDF image extraction needs PyMuPDF. Run: pip install pymupdf"
            ) from exc

    images: list[ExtractedImage] = []
    seen_xrefs: set[int] = set()
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            for page_number in range(doc.page_count):
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
                    suffix = f".{extracted.get('ext', 'png')}"
                    images.append(
                        ExtractedImage(
                            name=f"page{page_number + 1}_img{len(images) + 1}{suffix}",
                            data=blob,
                            source=f"page {page_number + 1}",
                            width=extracted.get("width"),
                            height=extracted.get("height"),
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
            name=image.name, source=image.source, width=image.width, height=image.height
        )
        try:
            result = describe_image_bytes(image.data, image.name, model=handle)
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
