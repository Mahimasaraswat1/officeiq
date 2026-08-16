"""Verification, face-match, and HR review schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import (
    DocumentStatus,
    FaceMatchStatus,
    OnboardingStatus,
    VerificationCheckType,
    VerificationStatus,
)

REJECTION_REASON_MIN_LENGTH = 10


class VerificationCheckRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    document_id: uuid.UUID | None = None
    check_type: VerificationCheckType
    status: VerificationStatus
    reason_code: str | None = None
    message: str | None = None
    provider: str
    reference_id: str | None = None
    masked_number: str | None = None
    name_similarity: float | None = None
    detail: dict | None = None
    created_at: datetime


class FaceMatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    photo_document_id: uuid.UUID | None = None
    id_document_id: uuid.UUID | None = None
    status: FaceMatchStatus
    similarity: float | None = None
    threshold: float | None = None
    engine: str | None = None
    message: str | None = None
    created_at: datetime


class DocumentReviewRequest(BaseModel):
    """HR approval. A reason is optional here but mandatory on rejection."""

    note: str | None = Field(default=None, max_length=1000)


class DocumentRejectRequest(BaseModel):
    """HR rejection — the reason is mandatory (PRD A.7.4)."""

    reason: str = Field(
        min_length=REJECTION_REASON_MIN_LENGTH,
        max_length=1000,
        description="Why the document was rejected. Shown to the employee.",
    )

    @field_validator("reason")
    @classmethod
    def _meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < REJECTION_REASON_MIN_LENGTH:
            raise ValueError(
                f"Please give a reason of at least {REJECTION_REASON_MIN_LENGTH} "
                "characters so the employee knows what to fix."
            )
        return cleaned


class DocumentReviewResult(BaseModel):
    document_id: uuid.UUID
    status: DocumentStatus
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None
    onboarding_status: OnboardingStatus
    message: str


class VerificationSummary(BaseModel):
    """Everything HR needs to decide on one employee, in a single response."""

    employee_id: uuid.UUID
    onboarding_status: OnboardingStatus

    id_checks: list[VerificationCheckRead] = Field(default_factory=list)
    face_match: FaceMatchRead | None = None

    documents_total: int = 0
    documents_approved: int = 0
    documents_rejected: int = 0
    documents_pending_review: int = 0

    missing_document_types: list[str] = Field(default_factory=list)

    # Task progress (Phase 4)
    tasks_total: int = 0
    tasks_completed: int = 0
    tasks_mandatory_outstanding: int = 0
    tasks_overdue: int = 0

    ready_for_completion: bool = False
    blocking_issues: list[str] = Field(default_factory=list)
