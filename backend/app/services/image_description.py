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

# Gemini accepts these inline. Anything else is skipped by the batch script.
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

# Inline request payload cap is ~20 MB; stay well under it.
MAX_IMAGE_BYTES = 15 * 1024 * 1024

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


def _mime_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed and guessed.startswith("image/"):
        return guessed
    # mimetypes misses .webp on some Windows/WSL setups.
    return {".webp": "image/webp", ".bmp": "image/bmp"}.get(
        path.suffix.lower(), "image/png"
    )


def describe_image(
    path: Path,
    model=None,
    model_name: str | None = None,
    prompt: str = PROMPT,
) -> Description:
    """Return a text description of the image at `path`.

    Pass a pre-built `model` when describing many images so the handle is
    reused; otherwise one is built per call.
    """
    data = path.read_bytes()
    if not data:
        raise ImageDescriptionError("file is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageDescriptionError(
            f"file is {len(data) / 1e6:.1f} MB, over the {MAX_IMAGE_BYTES / 1e6:.0f} MB inline limit"
        )

    handle = model if model is not None else build_model(model_name)
    response = handle.generate_content(
        [prompt, {"mime_type": _mime_type(path), "data": data}]
    )

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        # Usually a safety block or an empty candidate list.
        feedback = getattr(response, "prompt_feedback", None)
        raise ImageDescriptionError(f"model returned no text (feedback: {feedback})")

    return Description(text=text, model=getattr(handle, "model_name", model_name or settings.VISION_MODEL_NAME))
