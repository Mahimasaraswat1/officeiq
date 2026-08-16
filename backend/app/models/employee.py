"""Employee profile + onboarding invitation."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    Enum as SAEnum,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.core.database import Base
from app.core.types import TZDateTime
from app.models.enums import InvitationStatus, OnboardingStatus
from app.models.user import User

onboarding_status_enum = SAEnum(
    OnboardingStatus,
    name="onboarding_status",
    values_callable=lambda e: [m.value for m in e],
)

invitation_status_enum = SAEnum(
    InvitationStatus,
    name="invitation_status",
    values_callable=lambda e: [m.value for m in e],
)


class Employee(Base):
    """An employee's onboarding record, created by HR before the person registers."""

    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False
    )

    # Linked once the invited person completes registration.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), unique=True, index=True
    )

    # --- Identity ----------------------------------------------------------
    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)
    work_email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    personal_email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    date_of_birth: Mapped[date | None] = mapped_column(Date)

    # --- Address (pre-fillable from OCR in Phase 2) ------------------------
    address_line1: Mapped[str | None] = mapped_column(String(255))
    address_line2: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(80))
    postal_code: Mapped[str | None] = mapped_column(String(16))
    country: Mapped[str | None] = mapped_column(String(80), default="India")

    # --- Employment --------------------------------------------------------
    department: Mapped[str | None] = mapped_column(String(80), index=True)
    designation: Mapped[str | None] = mapped_column(String(80))
    date_of_joining: Mapped[date | None] = mapped_column(Date)
    reporting_manager: Mapped[str | None] = mapped_column(String(150))

    # --- Onboarding state --------------------------------------------------
    onboarding_status: Mapped[OnboardingStatus] = mapped_column(
        onboarding_status_enum,
        default=OnboardingStatus.INVITED,
        nullable=False,
        index=True,
    )
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    notes: Mapped[str | None] = mapped_column(Text)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User | None] = relationship(
        back_populates="employee", foreign_keys=[user_id]
    )
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    invitations: Mapped[list["Invitation"]] = relationship(
        back_populates="employee", cascade="all, delete-orphan"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Employee {self.employee_code} {self.full_name}>"


class Invitation(Base):
    """A one-time onboarding invite link emailed to a prospective employee."""

    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)

    # Only the SHA-256 hash is stored; the raw token lives solely in the email.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)

    status: Mapped[InvitationStatus] = mapped_column(
        invitation_status_enum, default=InvitationStatus.PENDING, nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(TZDateTime, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    sent_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )

    employee: Mapped[Employee] = relationship(back_populates="invitations")
    sent_by: Mapped[User | None] = relationship(foreign_keys=[sent_by_id])
