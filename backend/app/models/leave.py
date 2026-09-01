"""Per-employee, per-year leave balances.

One row per (employee, year, leave kind). Entitlements come from the handbook
the assistant quotes — 21 days annual, 12 sick — so the number the assistant
states and the number the app enforces cannot drift apart.

used_days is a stored counter rather than a figure derived from approved
requests on every read. It is written in the same transaction as the approval
that causes it, which keeps balance display O(1) and makes "deduct on approval"
a real transition rather than an emergent property. The risk of a stored
counter is drift, so app.services.leave.recompute_used_days() can rebuild it
from the requests, and a test asserts the two agree after a mixed sequence of
approvals, rejections and cancellations.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Enum as SAEnum,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.core.database import Base
from app.core.types import TZDateTime
from app.models.employee import Employee
from app.models.enums import LeaveKind

leave_kind_enum = SAEnum(
    LeaveKind,
    name="leave_kind",
    values_callable=lambda e: [m.value for m in e],
)

# Half-days are the smallest unit anyone books, and balances are added to and
# subtracted from repeatedly. Numeric is exact at one decimal place; float
# accumulates error across those operations and eventually shows 20.999999.
DAYS = Numeric(5, 1)


class LeaveBalance(Base):
    """What one employee is entitled to, and has used, for one kind in one year."""

    __tablename__ = "leave_balances"
    __table_args__ = (
        UniqueConstraint(
            "employee_id", "year", "leave_kind", name="uq_leave_balance_period"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), nullable=False, index=True
    )
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    leave_kind: Mapped[LeaveKind] = mapped_column(leave_kind_enum, nullable=False)

    # This year's allowance, pro-rated for anyone who joined part-way through.
    entitled_days: Mapped[Decimal] = mapped_column(DAYS, nullable=False, default=0)
    # Brought in from last year. Annual only, capped by policy at 10.
    carried_forward_days: Mapped[Decimal] = mapped_column(DAYS, nullable=False, default=0)
    # Approved and deducted.
    used_days: Mapped[Decimal] = mapped_column(DAYS, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    employee: Mapped[Employee] = relationship(Employee, lazy="joined")

    @property
    def total_days(self) -> Decimal:
        return self.entitled_days + self.carried_forward_days

    @property
    def available_days(self) -> Decimal:
        return self.total_days - self.used_days

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<LeaveBalance {self.leave_kind.value} {self.year} "
            f"{self.available_days}/{self.total_days}>"
        )
