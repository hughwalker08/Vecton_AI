"""
Vision service: turn an NCC/ABCB diagram or image into a text description.

Decided provider: Gemini via `google-generativeai` (settings.GEMINI_API_KEY),
same key as generation.py. The model is settings.VISION_MODEL_NAME.

The descriptions produced here are meant to be *ingested into the corpus*
alongside the clause text, so figures become retrievable and citable rather
than being dropped on the floor during parsing. That drives the prompt below:
verbatim transcription of every label/dimension/note beats prose summary,
because a user asking "what's the minimum riser height in Figure 11.2.2?"
needs the number to actually be in the indexed text.

Used by scripts/describe_images.py (batch CLI). Keep `describe_image`
importable and side-effect-free so the ingestion pipeline can call it later.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

# Bump when the prompt changes materially — it is recorded on every output row
# so you can tell which descriptions need regenerating after a prompt edit.
PROMPT_VERSION = "1"

# Formats Gemini accepts inline. Anything else is skipped by the batch script.
RASTER_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

# Vector formats we rasterise before sending. The NCC/ABCB corpus ships its
# figures as SVG (see app/ingest/corpus.py), so this is the common case there,
# not an edge case.
VECTOR_EXTENSIONS = {".svg"}

SUPPORTED_EXTENSIONS = RASTER_EXTENSIONS | VECTOR_EXTENSIONS

# Inline request payload cap is ~20 MB; stay well under it.
MAX_IMAGE_BYTES = 15 * 1024 * 1024

# Width to rasterise SVG at. NCC figures carry dimension text at small point
# sizes; rendering at native size makes those digits unreadable to the model,
# and misread digits are the failure mode that matters most here.
SVG_RENDER_WIDTH = 1600

PROMPT = """You are transcribing a figure from the National Construction Code (NCC) \
2025 Volume Two or the ABCB Housing Provisions Standard, for inclusion in a \
searchable compliance corpus used by Australian builders, certifiers and designers.

Produce a self-contained text description of the image using exactly these \
headings (omit a heading only if it genuinely does not apply):

## Figure
The figure/diagram number and title exactly as printed (e.g. "Figure 11.2.2: \
Stair riser and going dimensions"). Write "Not shown" if there is none.

## Type
What kind of image it is: section drawing, plan view, elevation, isometric, \
detail, flow chart, decision tree, table, graph, map, photograph, icon, etc.

## Description
What the figure depicts and what compliance point it illustrates. Describe the \
spatial arrangement concretely — which element sits above/below/inside which, \
the order of layers in an assembly, the direction of arrows and flows, what is \
being measured between which two points. A reader who cannot see the image must \
be able to reconstruct it from this text.

## Labels and annotations
Every piece of text in the image, transcribed verbatim, as a bullet list: part \
labels, callouts, leader-line notes, legend/key entries, axis labels, node text \
in flow charts, and any clause or standard references (e.g. "AS 1288", "Part \
10.2"). Do not paraphrase and do not omit any.

## Dimensions and values
Every measurement, angle, ratio, tolerance, load, and numeric range shown, with \
its units and what it applies to (e.g. "Riser height 190 mm max, measured from \
the top of one tread to the top of the next"). Include min/max qualifiers exactly \
as marked. Write "None shown" if the figure carries no numbers.

## Notes
Footnotes, asterisked qualifications, scale/NTS markers, and any applicability \
text (building classes, climate zones, states/territories) printed on the figure.

Rules:
- Transcribe only what is actually visible. Never infer a dimension, never fill \
in a value from your knowledge of the NCC, and never state a compliance \
requirement the figure does not show.
- If text is cut off or unreadable, transcribe what you can and mark the rest \
[illegible].
- If the image is a table, reproduce it as a markdown table under ## Description.
- Use Australian spelling and keep metric units as printed.
- Output plain markdown under the headings above. No preamble, no closing \
commentary, no code fences around the whole answer."""


# Gemini's recitation filter (finish_reason 4) blocks a share of NCC figures
# outright: the main prompt asks for verbatim transcription of labels, which is
# exactly the behaviour that filter exists to catch, and the NCC is
# copyrighted. This variant asks for the same six headings and the same facts
# -- dimensions, part names, spatial arrangement -- but frames the task as
# recording technical data rather than reproducing the document's text.
# Measurements and component names are facts, not creative expression.
#
# Use it only for figures the main prompt could not get through
# (`describe_images.py --fallback-prompt --retry-failed`). It is the weaker
# instruction: the main prompt produces fuller label lists when it works.
FALLBACK_PROMPT = """You are recording the technical content of an engineering
figure from an Australian building-code document, so that it can be found by
search. Report the facts the drawing conveys, in your own words.

Use exactly these headings (omit one only if it genuinely does not apply):

## Figure
The figure number and title shown at the top of the image.

## Type
Section drawing, plan view, elevation, isometric, detail, flow chart, decision
tree, table, graph, map or photograph.

## Description
What the drawing shows and what it is illustrating. Be concrete about the
spatial arrangement: which component sits above, below or inside which, the
order of layers in an assembly, what each arrow indicates, and which two points
each measurement runs between. A reader who cannot see the drawing should be
able to picture it.

## Labels and annotations
The components, materials and parts identified in the drawing, as a bullet
list. Name each one as the drawing names it. Include any standard or clause
numbers referenced.

## Dimensions and values
Every measurement, angle, ratio, tolerance and load shown, with its units and
what it applies to -- for example "riser height 190 mm maximum, measured from
the top of one tread to the top of the next". Keep minimum and maximum
qualifiers. Write "None shown" if the drawing carries no numbers.

## Notes
Any footnotes, scale markers, or statements about which building classes,
climate zones or states the drawing applies to.

Rules:
- Report only what the drawing actually shows. Never infer a dimension, never
  supply a value from general knowledge of the building code, and never state a
  requirement the drawing does not depict.
- Where text is unclear, say so with [illegible] rather than guessing.
- Use Australian spelling and keep metric units.
- Plain markdown under the headings above, no preamble or closing commentary."""


@dataclass
class Description:
    """One successful transcription."""

    text: str
    model: str
    prompt_version: str = PROMPT_VERSION


class ImageDescriptionError(RuntimeError):
    """Raised when an image could not be described."""


def build_model(model_name: str | None = None):
    """Configure and return a Gemini model handle.

    Imported lazily so `--dry-run` and `--help` work without the SDK installed
    or an API key set.
    """
    try:
        import google.generativeai as genai
    except ImportError as exc:  # pragma: no cover - environment issue
        raise ImageDescriptionError(
            "google-generativeai is not installed. Run: pip install -r requirements.txt"
        ) from exc

    if not settings.GEMINI_API_KEY:
        raise ImageDescriptionError(
            "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and fill it in (or export GEMINI_API_KEY)."
        )

    genai.configure(api_key=settings.GEMINI_API_KEY)
    return genai.GenerativeModel(model_name or settings.VISION_MODEL_NAME)


def mime_type_for(name: str) -> str:
    """Best-guess image MIME type for a file name."""
    guessed, _ = mimetypes.guess_type(name)
    if guessed and guessed.startswith("image/"):
        return guessed
    # mimetypes misses .webp on some Windows/WSL setups.
    return {".webp": "image/webp", ".bmp": "image/bmp", ".svg": "image/svg+xml"}.get(
        Path(name).suffix.lower(), "image/png"
    )


def rasterise_svg(data: bytes, width: int = SVG_RENDER_WIDTH) -> bytes:
    """Render SVG source to PNG bytes.

    Gemini cannot read SVG inline, so corpus figures have to be rasterised
    first. PyMuPDF does this with no native dependencies, which matters on
    Windows -- the obvious alternatives (cairosvg, svglib+reportlab) both end
    up needing a cairo build. cairosvg is still preferred when it happens to
    be installed, since it tracks the SVG spec more closely.
    """
    try:
        import cairosvg

        return cairosvg.svg2png(bytestring=data, output_width=width)
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - malformed SVG, missing fonts, etc.
        raise ImageDescriptionError(f"could not rasterise SVG: {exc}") from exc

    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf  # older PyMuPDF releases
        except ImportError as exc:
            raise ImageDescriptionError(
                "SVG support needs a renderer. Run: pip install pymupdf "
                "(or pip install cairosvg)."
            ) from exc

    try:
        with pymupdf.open(stream=data, filetype="svg") as doc:
            page = doc[0]
            if not page.rect.width:
                raise ImageDescriptionError("SVG has no drawable area")
            zoom = width / page.rect.width
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
            return pixmap.tobytes("png")
    except ImageDescriptionError:
        raise
    except Exception as exc:  # noqa: BLE001 - malformed SVG
        raise ImageDescriptionError(f"could not rasterise SVG: {exc}") from exc


def prepare_payload(data: bytes, name: str) -> tuple[bytes, str]:
    """Validate and, if needed, rasterise image bytes. Returns (bytes, mime_type).

    `name` is used only for its extension, so this works for bytes pulled
    straight out of an uploaded DOCX or PDF with no file on disk.
    """
    if not data:
        raise ImageDescriptionError("image is empty")

    if Path(name).suffix.lower() in VECTOR_EXTENSIONS:
        data = rasterise_svg(data)
        mime = "image/png"
    else:
        mime = mime_type_for(name)

    if len(data) > MAX_IMAGE_BYTES:
        raise ImageDescriptionError(
            f"image is {len(data) / 1e6:.1f} MB, over the "
            f"{MAX_IMAGE_BYTES / 1e6:.0f} MB inline limit"
        )
    return data, mime


CONTEXT_TEMPLATE = """

The document this image came from labels it:

    {caption}

That label is context from the surrounding document, NOT text printed on the
image. Use it to interpret what you are looking at, but do not transcribe it
into ## Labels and annotations or ## Figure unless the same text is actually
visible in the image itself."""

# When the caption is rendered inside the image -- as it is for figures cropped
# out of the NCC/ABCB PDFs, where the caption sits at the top of the crop --
# the fence above makes the model too cautious and it answers "Not shown" under
# ## Figure. Here the caption is printed text, and should be recorded as such.
CONTEXT_TEMPLATE_IN_IMAGE = """

This figure's caption is printed at the top of the image:

    {caption}

Record it under ## Figure exactly as printed. Transcribe the rest of the image
as normal."""


def with_caption(prompt: str, caption: str | None, caption_in_image: bool = False) -> str:
    """Append a caption to the prompt as clearly-external context.

    Worth doing: a caption like "Figure 12: Subfloor ventilation detail" tells
    the model what it is looking at, which measurably helps on a drawing that
    would otherwise be ambiguous. Worth fencing: the prompt's core rule is
    "transcribe only what is visible", and a caption pasted in unqualified
    invites the model to report it as printed text that isn't there.
    """
    if not caption or not caption.strip():
        return prompt
    template = CONTEXT_TEMPLATE_IN_IMAGE if caption_in_image else CONTEXT_TEMPLATE
    return prompt + template.format(caption=caption.strip())


def describe_image_bytes(
    data: bytes,
    name: str,
    model=None,
    model_name: str | None = None,
    prompt: str = PROMPT,
    caption: str | None = None,
    caption_in_image: bool = False,
) -> Description:
    """Describe image bytes that may never have touched the filesystem.

    This is the core call. `describe_image` wraps it for files on disk; the
    upload pipeline uses it directly for images pulled out of a DOCX or PDF.
    """
    payload, mime = prepare_payload(data, name)

    handle = model if model is not None else build_model(model_name)
    response = handle.generate_content(
        [with_caption(prompt, caption, caption_in_image), {"mime_type": mime, "data": payload}]
    )

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        # Usually a safety block or an empty candidate list.
        feedback = getattr(response, "prompt_feedback", None)
        raise ImageDescriptionError(f"model returned no text (feedback: {feedback})")

    return Description(
        text=text,
        model=getattr(handle, "model_name", model_name or settings.VISION_MODEL_NAME),
    )


def describe_image(
    path: Path,
    model=None,
    model_name: str | None = None,
    prompt: str = PROMPT,
    caption: str | None = None,
    caption_in_image: bool = False,
) -> Description:
    """Return a text description of the image at `path`.

    Pass a pre-built `model` when describing many images so the handle is
    reused; otherwise one is built per call. `caption` is the label the source
    document gave this figure, passed to the model as fenced external context.
    """
    return describe_image_bytes(
        path.read_bytes(), path.name, model=model, model_name=model_name,
        prompt=prompt, caption=caption, caption_in_image=caption_in_image,
    )
