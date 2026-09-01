"""Holiday calendar queries and the derived fields the UI reads.

"Today" comes from app.core.security.today_utc(), the app-wide definition, so a
holiday cannot be "upcoming" on one screen and "past" on another.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.security import today_utc
from app.models.enums import HolidayType
from app.models.holiday import Holiday
from app.schemas.holiday import HolidayRead, HolidayYearSummary

WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def today() -> date:
    """Kept as a local name for readability; the definition lives in one place."""
    return today_utc()


def _base_query(*, year: int | None, include_inactive: bool) -> Select:
    query = select(Holiday)
    if not include_inactive:
        query = query.where(Holiday.is_active.is_(True))
    if year is not None:
        # Range rather than extract(year) so the index on holiday_date is usable
        # and the behaviour is identical on SQLite and Postgres.
        query = query.where(
            Holiday.holiday_date >= date(year, 1, 1),
            Holiday.holiday_date <= date(year, 12, 31),
        )
    return query.order_by(Holiday.holiday_date)


def list_holidays(
    db: Session,
    *,
    year: int | None = None,
    include_inactive: bool = False,
) -> list[Holiday]:
    return list(db.scalars(_base_query(year=year, include_inactive=include_inactive)))


def to_read(holiday: Holiday, *, reference: date | None = None) -> HolidayRead:
    """Attach the derived date fields a client would otherwise compute itself."""
    reference = reference or today()
    delta = (holiday.holiday_date - reference).days
    return HolidayRead(
        id=holiday.id,
        name=holiday.name,
        holiday_date=holiday.holiday_date,
        type=holiday.type,
        description=holiday.description,
        is_active=holiday.is_active,
        is_past=delta < 0,
        days_until=delta if delta >= 0 else None,
        weekday=WEEKDAYS[holiday.holiday_date.weekday()],
    )


def year_summary(db: Session, *, year: int) -> HolidayYearSummary:
    """Counts for the page header, computed in one grouped query."""
    reference = today()
    rows = db.execute(
        select(Holiday.type, func.count())
        .where(
            Holiday.is_active.is_(True),
            Holiday.holiday_date >= date(year, 1, 1),
            Holiday.holiday_date <= date(year, 12, 31),
        )
        .group_by(Holiday.type)
    ).all()
    by_type = {holiday_type: count for holiday_type, count in rows}

    upcoming = db.scalar(
        select(func.count())
        .select_from(Holiday)
        .where(
            Holiday.is_active.is_(True),
            Holiday.holiday_date >= reference,
            Holiday.holiday_date <= date(year, 12, 31),
        )
    )

    return HolidayYearSummary(
        year=year,
        total=sum(by_type.values()),
        upcoming=upcoming or 0,
        public=by_type.get(HolidayType.PUBLIC, 0),
        restricted=by_type.get(HolidayType.RESTRICTED, 0),
        company=by_type.get(HolidayType.COMPANY, 0),
    )


def next_holiday(db: Session) -> Holiday | None:
    """The soonest holiday from today, for dashboard widgets."""
    return db.scalar(
        select(Holiday)
        .where(Holiday.is_active.is_(True), Holiday.holiday_date >= today())
        .order_by(Holiday.holiday_date)
        .limit(1)
    )


def find_clash(
    db: Session,
    *,
    holiday_date: date,
    name: str,
    exclude_id: uuid.UUID | None = None,
) -> Holiday | None:
    """An existing row that would violate the (date, name) constraint.

    Checked before insert so the user gets a readable 409 rather than a driver
    IntegrityError, and case-insensitively so "diwali" cannot shadow "Diwali".
    """
    query = select(Holiday).where(
        Holiday.holiday_date == holiday_date,
        func.lower(Holiday.name) == name.lower(),
    )
    if exclude_id is not None:
        query = query.where(Holiday.id != exclude_id)
    return db.scalar(query)
