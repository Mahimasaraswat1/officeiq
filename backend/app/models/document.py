"""Uploaded documents, per-field extraction results, and parsed resumes."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.core.database import Base
from app.core.types import TZDateTime
from app.models.employee import Employee
from app.models.enums import DocumentStatus, DocumentType, ExtractionSource
from app.models.user import User

json_type = JSON().with_variant(JSONB(), "postgresql")

document_type_enum = SAEnum(
    DocumentType, name="document_type", values_callable=lambda e: [m.value for m in e]
)
document_status_enum = SAEnum(
    DocumentStatus, name="document_status", values_callable=lambda e: [m.value for m in e]
)
extraction_source_enum = SAEnum(
    ExtractionSource,
    name="extraction_source",
    values_callable=lambda e: [m.value for m in e],
)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_type: Mapped[DocumentType] = mapped_column(
        document_type_enum, nullable=False, index=True
    )

    # --- Stored file -------------------------------------------------------
    # The client-supplied name, kept for display only — never used as a path.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    # --- Extraction --------------------------------------------------------
    status: Mapped[DocumentStatus] = mapped_column(
        document_status_enum, default=DocumentStatus.UPLOADED, nullable=False, index=True
    )
    extraction_source: Mapped[ExtractionSource | None] = mapped_column(extraction_source_enum)
    # Mean per-word OCR confidence for the whole document, 0.0-1.0.
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    raw_text: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    # --- HR review (Phase 3) ----------------------------------------------
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    # Mandatory whenever status is REJECTED (PRD A.7.4).
    rejection_reason: Mapped[str | None] = mapped_column(Text)

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    employee: Mapped[Employee] = relationship()
    uploaded_by: Mapped[User | None] = relationship(foreign_keys=[uploaded_by_id])
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_id])
    fields: Mapped[list["ExtractedField"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    resume_profile: Mapped["ResumeProfile | None"] = relationship(
        back_populates="document", cascade="all, delete-orphan", uselist=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Document {self.document_type.value} {self.original_filename}>"


class ExtractedField(Base):
    """One OCR-extracted field with its own confidence score (PRD B.4.3)."""

    __tablename__ = "extracted_fields"
    __table_args__ = (
        UniqueConstraint("document_id", "field_name", name="uq_extracted_field_per_document"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Maps to an Employee attribute where applicable (e.g. "date_of_birth").
    field_name: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str | None] = mapped_column(String(512))
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    source: Mapped[ExtractionSource] = mapped_column(extraction_source_enum, nullable=False)

    # HR/employee correction, kept separate so the original stays auditable.
    corrected_value: Mapped[str | None] = mapped_column(String(512))
    corrected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    corrected_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="fields")
    corrected_by: Mapped[User | None] = relationship(foreign_keys=[corrected_by_id])

    @property
    def effective_value(self) -> str | None:
        """The corrected value when present, otherwise what OCR produced."""
        return self.corrected_value if self.corrected_value is not None else self.value


class ResumeProfile(Base):
    """Structured output of resume parsing (PRD A.7.3)."""

    __tablename__ = "resume_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )

    candidate_name: Mapped[str | None] = mapped_column(String(150))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    total_experience_years: Mapped[float | None] = mapped_column(Float)

    # Lists of objects; shape is documented in schemas/document.py.
    education: Mapped[list | None] = mapped_column(json_type)
    experience: Mapped[list | None] = mapped_column(json_type)
    skills: Mapped[list | None] = mapped_column(json_type)

    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="resume_profile")
    employee: Mapped[Employee] = relationship()
