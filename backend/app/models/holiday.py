"""Company holiday calendar.

One row per holiday per year. Recurrence is not modelled on purpose: most
holidays here move against the Gregorian calendar (Diwali, Eid, Holi), so a
recurrence rule could not compute them anyway — HR enters each year's dates.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    Enum as SAEnum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.core.database import Base
from app.core.types import TZDateTime
from app.models.enums import HolidayType

holiday_type_enum = SAEnum(
    HolidayType,
    name="holiday_type",
    values_callable=lambda e: [m.value for m in e],
)


class Holiday(Base):
    """A single dated holiday in the company calendar."""

    __tablename__ = "holidays"
    __table_args__ = (
        # Two festivals can fall on one day, so the date alone is not unique.
        UniqueConstraint("holiday_date", "name", name="uq_holiday_date_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    type: Mapped[HolidayType] = mapped_column(
        holiday_type_enum, default=HolidayType.PUBLIC, nullable=False, index=True
    )
    description: Mapped[str | None] = mapped_column(Text)

    # Soft delete. A holiday removed today must not disappear from last year's
    # calendar, which people still refer back to.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Holiday {self.holiday_date} {self.name!r}>"
