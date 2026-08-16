"""Mock ID verification results and photo-vs-ID face match results."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.core.database import Base
from app.core.types import TZDateTime
from app.models.document import Document
from app.models.employee import Employee
from app.models.enums import FaceMatchStatus, VerificationCheckType, VerificationStatus
from app.models.user import User

json_type = JSON().with_variant(JSONB(), "postgresql")

check_type_enum = SAEnum(
    VerificationCheckType,
    name="verification_check_type",
    values_callable=lambda e: [m.value for m in e],
)
verification_status_enum = SAEnum(
    VerificationStatus,
    name="verification_status",
    values_callable=lambda e: [m.value for m in e],
)
face_match_status_enum = SAEnum(
    FaceMatchStatus,
    name="face_match_status",
    values_callable=lambda e: [m.value for m in e],
)


class VerificationCheck(Base):
    """One mock Aadhaar/PAN check.

    Rows are kept as history rather than overwritten, so re-running a check
    after a correction leaves an auditable trail of both attempts.
    """

    __tablename__ = "verification_checks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )

    check_type: Mapped[VerificationCheckType] = mapped_column(
        check_type_enum, nullable=False, index=True
    )
    status: Mapped[VerificationStatus] = mapped_column(
        verification_status_enum, nullable=False, index=True
    )
    reason_code: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str | None] = mapped_column(Text)

    # Always the mock provider in v1; recorded so a mock result can never be
    # mistaken for a real government verification.
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_id: Mapped[str | None] = mapped_column(String(64), index=True)

    # Only the masked form is stored — the full ID number is never persisted.
    masked_number: Mapped[str | None] = mapped_column(String(32))
    name_similarity: Mapped[float | None] = mapped_column(Float)

    detail: Mapped[dict | None] = mapped_column(json_type)

    performed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), index=True, nullable=False
    )

    employee: Mapped[Employee] = relationship()
    document: Mapped[Document | None] = relationship()
    performed_by: Mapped[User | None] = relationship(foreign_keys=[performed_by_id])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<VerificationCheck {self.check_type.value} {self.status.value}>"


class FaceMatch(Base):
    """One photo-vs-ID face comparison (PRD A.7.4)."""

    __tablename__ = "face_matches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    photo_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    id_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )

    status: Mapped[FaceMatchStatus] = mapped_column(
        face_match_status_enum, nullable=False, index=True
    )
    similarity: Mapped[float | None] = mapped_column(Float)
    # Persisted alongside the score so a later config change cannot silently
    # reinterpret a historical result.
    threshold: Mapped[float | None] = mapped_column(Float)

    engine: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(json_type)

    performed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), index=True, nullable=False
    )

    employee: Mapped[Employee] = relationship()
    photo_document: Mapped[Document | None] = relationship(
        foreign_keys=[photo_document_id]
    )
    id_document: Mapped[Document | None] = relationship(foreign_keys=[id_document_id])
    performed_by: Mapped[User | None] = relationship(foreign_keys=[performed_by_id])

    @property
    def passed(self) -> bool:
        return self.status is FaceMatchStatus.MATCHED
