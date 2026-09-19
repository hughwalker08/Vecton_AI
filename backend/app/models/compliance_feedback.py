"""
SQLAlchemy model for a flagged compliance_analysis finding.

A reviewer who disagrees with a finding's classification (addressed /
missing / contradicted / needs_review -- see
app/services/compliance_analysis.py) can flag it here for follow-up. Not
linked to a logged-in user: unlike user_profiles (tied to Supabase Auth),
the API routes have no auth wired in yet, so this is a flat, reviewable log
rather than a per-user table.

Schema: migrations/versions/0006_compliance_feedback.py
"""

import uuid

from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.sql import func

from app.db.session import Base


class ComplianceFeedback(Base):
    __tablename__ = "compliance_feedback"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Which finding this is about -- app.services.compliance_analysis.ComplianceFinding.
    clause_id = Column(String, nullable=False, index=True)
    doc = Column(String)
    query = Column(Text, nullable=False)  # the analyse_document() query that produced it
    reported_status = Column(String, nullable=False)  # the status being flagged as wrong
    corrected_status = Column(String)  # what the reviewer thinks it should be, if known
    comment = Column(Text)

    created_at = Column(DateTime, server_default=func.now())
