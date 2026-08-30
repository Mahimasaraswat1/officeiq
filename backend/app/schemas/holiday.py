"""Holiday calendar request/response contracts."""

from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import HolidayType


class HolidayBase(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    holiday_date: date
    type: HolidayType = HolidayType.PUBLIC
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        """Trim before length checks bite, so " Diwali " is not a distinct holiday."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Name cannot be blank.")
        return cleaned


class HolidayCreate(HolidayBase):
    pass


class HolidayUpdate(BaseModel):
    """Every field optional — PATCH semantics, absent means unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    holiday_date: date | None = None
    type: HolidayType | None = None
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None

    _strip_name = field_validator("name")(HolidayBase._strip_name.__func__)


class HolidayRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    holiday_date: date
    type: HolidayType
    description: str | None = None
    is_active: bool

    # Derived for the UI so every client does not reimplement the same date
    # arithmetic (and disagree with the server about "today").
    is_past: bool
    days_until: int | None = Field(
        default=None,
        description="Whole days from today; 0 is today, null once the date has passed",
    )
    weekday: str


class HolidayYearSummary(BaseModel):
    """Header counts for the calendar page."""

    year: int
    total: int
    upcoming: int
    public: int
    restricted: int
    company: int
