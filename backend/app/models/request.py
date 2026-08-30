"""Generic employee request with a single approval step.

One table serves every request type. The type-specific fields live in `payload`
and are validated on the way in by a per-type Pydantic model (see
app.services.requests), so adding WFH or an equipment request means registering
a payload model — not another table, another router, and another copy of the
approve/reject logic.

The alternative considered was a DB-driven form builder (request types and their
fields as rows). It buys a type without a migration, at the cost of a dynamic
form renderer and the loss of typed validation. For a fixed, small set of types
that trade is not worth it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Enum as SAEnum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.core.database import Base
from app.core.types import TZDateTime
from app.models.employee import Employee
from app.models.enums import RequestStatus, RequestType
from app.models.user import User

request_type_enum = SAEnum(
    RequestType,
    name="request_type",
    values_callable=lambda e: [m.value for m in e],
)

request_status_enum = SAEnum(
    RequestStatus,
    name="request_status",
    values_callable=lambda e: [m.value for m in e],
)


class Request(Base):
    """Something an employee has asked for, and what was decided about it."""

    __tablename__ = "requests"
    __table_args__ = (
        # The approval queue filters on exactly this pair.
        Index("ix_requests_status_type", "status", "type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False
    )
    type: Mapped[RequestType] = mapped_column(request_type_enum, nullable=False, index=True)

    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[RequestStatus] = mapped_column(
        request_status_enum, default=RequestStatus.PENDING, nullable=False, index=True
    )

    # Type-specific fields. Validated against the type's payload model on write,
    # so nothing unvalidated reaches the column.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # A human line written once at submit. The approval queue and the
    # notification both need it without knowing how to read a leave payload.
    summary: Mapped[str] = mapped_column(String(255), nullable=False)

    # Null means "the HR/Admin pool". This is the hook for a future manager
    # hierarchy: routing changes here, and nothing downstream has to know.
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    submitted_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    decision_note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    employee: Mapped[Employee] = relationship(Employee, lazy="joined")
    decided_by: Mapped[User | None] = relationship(
        User, foreign_keys=[decided_by_id], lazy="joined"
    )
    assigned_to: Mapped[User | None] = relationship(
        User, foreign_keys=[assigned_to_id], lazy="joined"
    )

    @property
    def is_open(self) -> bool:
        """Still awaiting a decision — the only state that can be acted on."""
        return self.status is RequestStatus.PENDING

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Request {self.request_code} {self.type.value} {self.status.value}>"
