"""
Tests for caption detection and for matching captions to images.

The caption-matching tests build real DOCX and PDF bytes rather than mocking
the containers, because the whole problem being solved here is positional --
which paragraph sits next to the drawing, which text block sits under the
figure. A mock that returns "the caption" would test nothing.
"""

import io
import zipfile

import pytest

from app.services import document_captions as dc
from app.services.document_images import extract_from_docx, extract_from_pdf

# --------------------------------------------------------------------------
# looks_like_caption
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Figure 12: Subfloor ventilation detail",
        "Figure 3.2 - Wall junction",
        "FIGURE 7",
        "Fig. 4 — Stair section",
        "Table 7.2: Minimum clearances",
        "Detail 5",
        "Drawing A-101: Ground floor plan",
        "Diagram 2 – Flashing at sill",
        "Photo 3: Existing eaves",
    ],
)
def test_recognises_caption_shapes_used_in_construction_documents(text):
    assert dc.looks_like_caption(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "The subfloor must be ventilated in accordance with Part 6.2.",
        "Figures are indicative only and not to scale",
        "See the drawing on the following page for the junction detail.",
        "x" * 400,  # too long to be a label
    ],
)
def test_rejects_prose_that_merely_mentions_figures(text):
    assert not dc.looks_like_caption(text)


# --------------------------------------------------------------------------
# Candidate sources
# --------------------------------------------------------------------------


def test_alt_text_is_trusted_above_everything_else():
    authored = dc.from_alt_text("Subfloor ventilation detail", "Picture 3")
    assert authored.source == "alt-text"
    assert authored.confidence > dc.SOURCE_CONFIDENCE["caption-style"]


@pytest.mark.parametrize("placeholder", ["Picture 3", "image1.png", "Graphic", "Chart 2", "diagram"])
def test_word_placeholder_alt_text_is_not_a_caption(placeholder):
    """Word autogenerates these; they name the shape, they don't describe it."""
    assert dc.from_alt_text(placeholder) is None


def test_caption_style_is_trusted_without_matching_the_pattern():
    """An explicit Caption style is authored intent, whatever the wording."""
    found = dc.from_paragraph("Ventilation of the subfloor space", style="Caption")
    assert found is not None
    assert found.source == "caption-style"


def test_unstyled_paragraph_must_look_like_a_caption():
    assert dc.from_paragraph("The subfloor must be ventilated.", style="Normal") is None
    assert dc.from_paragraph("Figure 9: Vent spacing", style="Normal").source == "caption-pattern"


def test_text_far_below_an_image_is_only_taken_when_it_looks_like_a_caption():
    assert dc.from_nearby_text("Some ordinary body text", distance=100, below=True) is None
    assert dc.from_nearby_text("Figure 4: Vent spacing", distance=100, below=True) is not None


def test_text_above_an_image_needs_the_caption_pattern():
    """Captions sit under figures far more often than over them."""
    assert dc.from_nearby_text("Ordinary body text", distance=10, below=False) is None
    assert dc.from_nearby_text("Figure 4: Vent spacing", distance=10, below=False) is not None


def test_weak_candidates_are_dropped_rather_than_guessed_at():
    """A wrong caption attributes a drawing to the wrong requirement."""
    weak = dc.Caption(text="maybe", source="nearby-text", confidence=0.1)
    assert dc.best_caption([weak]) is None
    assert dc.best_caption([]) is None


def test_best_caption_prefers_the_most_trustworthy_source():
    chosen = dc.best_caption(
        [
            dc.Caption("near", "nearby-text", dc.SOURCE_CONFIDENCE["nearby-text"]),
            dc.Caption("authored", "alt-text", dc.SOURCE_CONFIDENCE["alt-text"]),
            dc.Caption("pattern", "caption-pattern", dc.SOURCE_CONFIDENCE["caption-pattern"]),
        ]
    )
    assert chosen.text == "authored"


# --------------------------------------------------------------------------
# DOCX: real archives, real document order
# --------------------------------------------------------------------------

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"

_PNG_HEADER = bytes.fromhex("89504e470d0a1a0a0000000d49484452")


def _png(width=400, height=300, padding=20000):
    """A PNG with a readable header, padded past the decorative-image floor."""
    return (
        _PNG_HEADER
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
        + b"\x00" * padding
    )


def _paragraph(text="", style=None, drawing_rel=None, alt=None, shape_name=None):
    style_xml = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    drawing_xml = ""
    if drawing_rel:
        descr = f' descr="{alt}"' if alt else ""
        name = f' name="{shape_name}"' if shape_name else ""
        drawing_xml = (
            f"<w:r><w:drawing><wp:inline>"
            f"<wp:docPr id=\"1\"{name}{descr}/>"
            f'<a:graphic><a:graphicData><pic:pic xmlns:pic="urn:pic">'
            f'<pic:blipFill><a:blip r:embed="{drawing_rel}"/></pic:blipFill>'
            f"</pic:pic></a:graphicData></a:graphic>"
            f"</wp:inline></w:drawing></w:r>"
        )
    text_xml = f"<w:r><w:t>{text}</w:t></w:r>" if text else ""
    return f"<w:p>{style_xml}{text_xml}{drawing_xml}</w:p>"


def _docx(paragraphs, media):
    """Build a minimal but structurally real DOCX."""
    body = "".join(paragraphs)
    document = (
        f'<?xml version="1.0"?>'
        f'<w:document xmlns:w="{_W}" xmlns:a="{_A}" xmlns:r="{_R}" xmlns:wp="{_WP}">'
        f"<w:body>{body}</w:body></w:document>"
    )
    rels = ['<?xml version="1.0"?>', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for rel_id, target in media:
        rels.append(
            f'<Relationship Id="{rel_id}" Type="http://schemas.openxmlformats.org/officeDocument/'
            f'2006/relationships/image" Target="media/{target}"/>'
        )
    rels.append("</Relationships>")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/_rels/document.xml.rels", "".join(rels))
        for _, target in media:
            archive.writestr(f"word/media/{target}", _png())
    return buffer.getvalue()


def test_docx_caption_comes_from_the_paragraph_below_the_image():
    """The conventional placement: image, then its caption underneath."""
    data = _docx(
        [
            _paragraph("Subfloor ventilation is required."),
            _paragraph(drawing_rel="rId1"),
            _paragraph("Figure 12: Subfloor ventilation detail", style="Caption"),
        ],
        [("rId1", "image1.png")],
    )
    images = extract_from_docx(data)

    assert len(images) == 1
    assert images[0].caption_text == "Figure 12: Subfloor ventilation detail"
    assert images[0].caption.source == "caption-style"


def test_docx_alt_text_wins_over_a_nearby_caption_paragraph():
    """Alt text describes that exact drawing; a neighbouring paragraph may not."""
    data = _docx(
        [
            _paragraph(drawing_rel="rId1", alt="Vent spacing at 1.5m centres"),
            _paragraph("Figure 12: Subfloor ventilation detail", style="Caption"),
        ],
        [("rId1", "image1.png")],
    )
    images = extract_from_docx(data)

    assert images[0].caption_text == "Vent spacing at 1.5m centres"
    assert images[0].caption.source == "alt-text"


def test_docx_ignores_word_placeholder_shape_names():
    data = _docx(
        [
            _paragraph(drawing_rel="rId1", shape_name="Picture 3"),
            _paragraph("Figure 12: Subfloor ventilation detail", style="Caption"),
        ],
        [("rId1", "image1.png")],
    )
    assert extract_from_docx(data)[0].caption.source == "caption-style"


def test_docx_image_with_no_caption_anywhere_gets_none():
    data = _docx(
        [
            _paragraph("Some ordinary body text about ventilation."),
            _paragraph(drawing_rel="rId1"),
            _paragraph("More ordinary body text that is not a caption."),
        ],
        [("rId1", "image1.png")],
    )
    assert extract_from_docx(data)[0].caption is None


def test_docx_keeps_document_order_and_matches_each_image_to_its_own_caption():
    data = _docx(
        [
            _paragraph(drawing_rel="rId1"),
            _paragraph("Figure 1: Eaves detail", style="Caption"),
            _paragraph(drawing_rel="rId2"),
            _paragraph("Figure 2: Sill flashing", style="Caption"),
        ],
        [("rId1", "image1.png"), ("rId2", "image2.png")],
    )
    images = extract_from_docx(data)

    assert [i.caption_text for i in images] == ["Figure 1: Eaves detail", "Figure 2: Sill flashing"]


def test_docx_media_never_referenced_from_the_body_is_still_extracted():
    """Header and textbox images have no document position, but still count."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f'<w:document xmlns:w="{_W}"><w:body><w:p/></w:body></w:document>',
        )
        archive.writestr("word/media/orphan.png", _png())
    images = extract_from_docx(buffer.getvalue())

    assert len(images) == 1
    assert images[0].caption is None


def test_docx_corrupt_archive_is_reported_clearly():
    from app.services.document_images import DocumentImageError

    with pytest.raises(DocumentImageError, match="bad zip archive"):
        extract_from_docx(b"definitely not a zip file")


# --------------------------------------------------------------------------
# PDF: real pages, real geometry
# --------------------------------------------------------------------------


def _pdf_with_caption(caption_text, *, below=True, gap=10):
    """A one-page PDF with an image and a line of text near it."""
    pymupdf = pytest.importorskip("pymupdf")

    doc = pymupdf.open()
    page = doc.new_page()
    image_rect = pymupdf.Rect(100, 200, 400, 400)
    page.insert_image(image_rect, stream=_png_pixels())
    y = image_rect.y1 + gap if below else image_rect.y0 - gap
    page.insert_text((105, y), caption_text, fontsize=9)
    data = doc.tobytes()
    doc.close()
    return data


def _png_pixels():
    """A real, decodable PNG big enough to clear the decorative floor."""
    pymupdf = pytest.importorskip("pymupdf")
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 300))
    pixmap.set_rect(pixmap.irect, (200, 120, 60))
    return pixmap.tobytes("png")


def test_pdf_caption_is_taken_from_text_under_the_image():
    images = extract_from_pdf(_pdf_with_caption("Figure 12: Subfloor ventilation detail"))

    assert len(images) == 1
    assert images[0].caption is not None
    assert "Subfloor ventilation detail" in images[0].caption_text


def test_pdf_body_text_far_under_an_image_is_not_taken_as_its_caption():
    images = extract_from_pdf(
        _pdf_with_caption("The subfloor must be ventilated in accordance with Part 6.2.", gap=100)
    )
    assert images[0].caption is None


def test_pdf_caption_above_the_image_is_accepted_when_it_looks_like_one():
    images = extract_from_pdf(_pdf_with_caption("Figure 8: Eaves detail", below=False, gap=15))
    assert images[0].caption is not None
    assert "Eaves detail" in images[0].caption_text


def test_pdf_with_no_text_near_the_image_gets_no_caption():
    pymupdf = pytest.importorskip("pymupdf")

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(pymupdf.Rect(100, 200, 400, 400), stream=_png_pixels())
    data = doc.tobytes()
    doc.close()

    images = extract_from_pdf(data)
    assert len(images) == 1
    assert images[0].caption is None


def test_pdf_that_is_not_a_pdf_is_reported_clearly():
    from app.services.document_images import DocumentImageError

    with pytest.raises(DocumentImageError, match="could not read PDF"):
        extract_from_pdf(b"not a pdf at all")
