"""
Document upload endpoint skeleton.

Intended flow (see planning doc, Part B - User document uploads):
    1. Accept a PDF or DOCX file.
    2. Parse to text - DOCX via python-docx, PDF via Docling or LlamaParse
       (provider chosen by settings.PDF_PARSER).
    3. Chunk and embed the same way as the ingested NCC/ABCB corpus.
    4. Analyse against applicable provisions, producing categorised findings.

None of this is implemented yet - just the route shape and schema.
"""

from fastapi import APIRouter, UploadFile, File
from pydantic import BaseModel

router = APIRouter()


class UploadResponse(BaseModel):
    filename: str
    status: str


@router.post("/", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)) -> UploadResponse:
    """Placeholder - not yet wired up to parsing or analysis."""
    return UploadResponse(filename=file.filename, status="received (not processed - not implemented yet)")
