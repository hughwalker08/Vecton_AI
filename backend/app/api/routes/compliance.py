"""
Compliance analysis endpoint.

Classifies a document's text against the NCC/ABCB requirement clauses
applicable to `query` (optionally scoped to a jurisdiction), producing
findings: addressed / missing / contradicted / needs_review. See
app.services.compliance_analysis for the classification logic.

Upload text extraction (api/routes/upload.py) is not wired up yet, so this
endpoint takes already-extracted `document_text` directly rather than a
file -- once upload.py can produce text, it becomes the caller here.

Also exposes a small feedback log (POST/GET /feedback, table
compliance_feedback, migration 0006) so a reviewer who disagrees with a
finding's classification can flag it for follow-up -- not tied to a
logged-in user, since no auth is wired into these routes yet.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.compliance_feedback import ComplianceFeedback
from app.services.compliance_analysis import STATUSES, ComplianceAnalysisError, analyse_document
from app.services.compliance_analysis import QuotaExceededError as AnalysisQuotaExceeded
from app.services.embedding import EmbeddingError
from app.services.embedding import QuotaExceededError as EmbeddingQuotaExceeded
from app.services.retrieval import QuotaExceededError as RerankQuotaExceeded
from app.services.retrieval import RerankError

router = APIRouter()

RETRIEVAL_TOP_K = 10

FindingStatus = Literal["addressed", "missing", "contradicted", "needs_review"]

Jurisdiction = Literal[
    "ACT",
    "NSW",
    "NT",
    "QLD",
    "SA",
    "TAS",
    "VIC",
    "WA",
]


class ComplianceRequest(BaseModel):
    document_text: str
    query: str
    jurisdiction: Jurisdiction | None = None


class Finding(BaseModel):
    clause_id: str
    doc: str
    status: FindingStatus
    explanation: str
    heading: str | None = None
    evidence: str | None = None
    source_url: str | None = None


class ComplianceResponse(BaseModel):
    query: str
    jurisdiction: str | None = None
    findings: list[Finding] = []
    counts: dict[str, int] = dict.fromkeys(STATUSES, 0)


@router.post("/analyse", response_model=ComplianceResponse)
def analyse(request: ComplianceRequest) -> ComplianceResponse:
    """Classify the applicable requirements against a document's extracted text."""
    document_text = request.document_text.strip()
    if not document_text:
        raise HTTPException(status_code=400, detail="document_text must not be empty.")
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query must not be empty.")

    try:
        report = analyse_document(
            document_text, query, jurisdiction=request.jurisdiction, top_k=RETRIEVAL_TOP_K
        )
    except (EmbeddingQuotaExceeded, RerankQuotaExceeded, AnalysisQuotaExceeded) as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except (EmbeddingError, RerankError, ComplianceAnalysisError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return ComplianceResponse(
        query=report.query,
        jurisdiction=report.jurisdiction,
        findings=[
            Finding(
                clause_id=f.clause_id,
                doc=f.doc,
                status=f.status,
                explanation=f.explanation,
                heading=f.heading,
                evidence=f.evidence,
                source_url=f.source_url,
            )
            for f in report.findings
        ],
        counts=report.counts,
    )


class FeedbackRequest(BaseModel):
    clause_id: str
    query: str
    reported_status: FindingStatus  # the status on the finding being flagged
    doc: str | None = None
    corrected_status: FindingStatus | None = None  # what the reporter thinks it should be
    comment: str | None = None


class FeedbackResponse(BaseModel):
    id: str
    clause_id: str
    doc: str | None = None
    query: str
    reported_status: str
    corrected_status: str | None = None
    comment: str | None = None
    created_at: datetime | None = None


def _feedback_response(row: ComplianceFeedback) -> FeedbackResponse:
    return FeedbackResponse(
        id=row.id,
        clause_id=row.clause_id,
        doc=row.doc,
        query=row.query,
        reported_status=row.reported_status,
        corrected_status=row.corrected_status,
        comment=row.comment,
        created_at=row.created_at,
    )


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
def flag_finding(request: FeedbackRequest, db: Session = Depends(get_db)) -> FeedbackResponse:
    """Record a reviewer's disagreement with a finding's classification."""
    row = ComplianceFeedback(
        id=str(uuid.uuid4()),
        clause_id=request.clause_id,
        doc=request.doc,
        query=request.query,
        reported_status=request.reported_status,
        corrected_status=request.corrected_status,
        comment=request.comment,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _feedback_response(row)


@router.get("/feedback", response_model=list[FeedbackResponse])
def list_feedback(
    clause_id: str | None = None, db: Session = Depends(get_db)
) -> list[FeedbackResponse]:
    """List flagged findings, most recent first, optionally filtered by clause_id."""
    q = db.query(ComplianceFeedback)
    if clause_id:
        q = q.filter(ComplianceFeedback.clause_id == clause_id)
    rows = q.order_by(ComplianceFeedback.created_at.desc()).all()
    return [_feedback_response(row) for row in rows]
