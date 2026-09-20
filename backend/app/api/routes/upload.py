"""
Document upload endpoint.

Intended flow (see planning doc, Part B - User document uploads):
    1. Accept a PDF or DOCX file.
    2a. Parse to text - DOCX via python-docx, PDF via PyMuPDF.  IMPLEMENTED
    2b. Extract embedded images, match each to its caption in the
        document, and transcribe it.                          IMPLEMENTED
    3. Chunk and embed (Gemini text-embedding-004) the same way as the
       ingested NCC/ABCB corpus.                              NOT IMPLEMENTED
    4. Analyse against applicable provisions, producing categorised findings.
                                                              NOT IMPLEMENTED

Step 2b is live: uploaded drawings are run through the same vision service
that transcribes the NCC/ABCB corpus figures, so a submitted plan set's
dimensions and annotations come back as text, anchored to the caption the
document gave them ("Figure 12: Subfloor ventilation detail"). The caption is
what lets a description be tied back to the requirement it is evidence for.

Step 2a is a lightweight extraction (services/document_text.py) built for the
chat-attachment feature: the text is returned to the caller as-is rather than
spliced with image descriptions or fed into compliance_analysis.py. The
heavier LlamaParse-based pipeline described in settings.PDF_PARSER is still
not wired up, and remains the plan for step 3/4's chunk-and-embed path.
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.services.document_images import (
    SUPPORTED_DOCUMENTS,
    DocumentImageError,
    describe_document_images,
)
from app.services.document_text import extract_text
from app.services.image_description import ImageDescriptionError

router = APIRouter()

# A plan set can carry hundreds of images. Cap what one request will transcribe
# so an upload can't quietly run up a large bill or a multi-minute response;
# the cap is reported back so the caller knows the result was truncated.
DEFAULT_MAX_IMAGES = 25


class ImageFindingResponse(BaseModel):
    name: str
    source: str
    description: str | None = None
    error: str | None = None
    # What the document called this drawing, when it could be matched.
    caption: str | None = None
    # How it was matched: "alt-text" and "caption-style" are authored by the
    # document's writer; "caption-pattern" and "nearby-text" are inferred from
    # position, so a reviewer should weigh them accordingly.
    caption_source: str | None = None


class UploadResponse(BaseModel):
    filename: str
    status: str
    # The document's own extracted text (services/document_text.py) -- named
    # for the step it reports on, not just a status string.
    text_extraction: str
    images_found: int = 0
    images_skipped: int = 0
    images_described: int = 0
    images_failed: int = 0
    images_captioned: int = 0
    truncated: bool = False
    images: list[ImageFindingResponse] = []


@router.post("/", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    describe_images: bool = Query(
        True, description="Transcribe embedded images (costs one LLM call each)."
    ),
    max_images: int = Query(
        DEFAULT_MAX_IMAGES, ge=1, le=200, description="Cap on images transcribed."
    ),
) -> UploadResponse:
    """Accept a PDF or DOCX, and transcribe the drawings inside it."""
    filename = file.filename or "upload"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        extracted_text = extract_text(data, filename)
    except Exception as exc:  # noqa: BLE001 - wrong/corrupt/unreadable file
        raise HTTPException(
            status_code=400, detail=f"Could not extract text from {filename}: {exc}"
        ) from exc

    response = UploadResponse(
        filename=filename,
        status="received",
        text_extraction=extracted_text,
    )

    if not describe_images:
        response.status = "received - image transcription skipped"
        return response

    try:
        report = describe_document_images(
            data, filename, max_images=max_images
        )
    except DocumentImageError as exc:
        # Wrong file type, corrupt archive, or a missing extraction library.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ImageDescriptionError as exc:
        # Vision provider is not configured - a server-side problem, not the
        # caller's. Surfaced explicitly rather than as a generic 500.
        raise HTTPException(
            status_code=503, detail=f"Image transcription unavailable: {exc}"
        ) from exc

    response.images_found = report.images_found
    response.images_skipped = report.images_skipped
    response.images_described = report.described
    response.images_failed = report.failed
    response.images_captioned = report.captioned
    response.truncated = (
        report.images_found - report.images_skipped
    ) > len(report.findings)
    response.images = [
        ImageFindingResponse(
            name=f.name,
            source=f.source,
            description=f.description,
            error=f.error,
            caption=f.caption,
            caption_source=f.caption_source,
        )
        for f in report.findings
    ]
    response.status = (
        f"processed {report.described} image(s) from {filename}"
        if report.described
        else f"no transcribable images found in {filename}"
    )
    return response


@router.get("/supported-types")
async def supported_types() -> dict:
    """Document types this endpoint can extract images from."""
    return {"document_types": sorted(SUPPORTED_DOCUMENTS)}
