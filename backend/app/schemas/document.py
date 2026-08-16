"""Document, extraction, and resume schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.models.enums import DocumentStatus, DocumentType, ExtractionSource


class ExtractedFieldRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    field_name: str
    value: str | None = None
    corrected_value: str | None = None
    confidence: float
    source: ExtractionSource
    corrected_at: datetime | None = None


class ExtractedFieldOut(ExtractedFieldRead):
    """Adds derived fields the HR review UI needs."""

    effective_value: str | None = None
    is_low_confidence: bool = False

    @classmethod
    def from_model(cls, model) -> "ExtractedFieldOut":
        return cls(
            id=model.id,
            field_name=model.field_name,
            value=model.value,
            corrected_value=model.corrected_value,
            confidence=model.confidence,
            source=model.source,
            corrected_at=model.corrected_at,
            effective_value=model.effective_value,
            is_low_confidence=model.confidence < settings.OCR_LOW_CONFIDENCE_THRESHOLD,
        )


class ResumeProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_name: str | None = None
    email: str | None = None
    phone: str | None = None
    total_experience_years: float | None = None
    # education: [{degree, institution, year, cgpa?, percentage?, detail}]
    education: list[dict] | None = None
    # experience: [{title, start_year, end_year, is_current, duration_years, detail}]
    experience: list[dict] | None = None
    skills: list[str] | None = None
    confidence: float


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    document_type: DocumentType
    original_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    status: DocumentStatus
    extraction_source: ExtractionSource | None = None
    ocr_confidence: float | None = None
    error_message: str | None = None
    processed_at: datetime | None = None
    # HR review (Phase 3)
    reviewed_by_id: uuid.UUID | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentRead):
    """Full record including extraction output, for the review screen."""

    fields: list[ExtractedFieldOut] = Field(default_factory=list)
    resume_profile: ResumeProfileRead | None = None
    raw_text_preview: str | None = None


class DownloadLink(BaseModel):
    url: str
    expires_in_seconds: int


class FieldCorrection(BaseModel):
    """Manual correction of one extracted field."""

    corrected_value: str | None = Field(default=None, max_length=512)


class ApplyExtractionRequest(BaseModel):
    """Copy chosen extracted fields onto the employee profile (PRD A.6 step 4)."""

    field_names: list[str] | None = Field(
        default=None,
        description="Which fields to apply. Defaults to every mappable field.",
    )
    # Guards against silently writing a low-confidence OCR value onto a profile.
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ApplyExtractionResponse(BaseModel):
    applied: dict[str, str]
    skipped: dict[str, str]
    message: str
