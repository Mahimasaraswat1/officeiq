"""Company holiday calendar.

Reading is open to every signed-in role — the calendar is company-wide
information and an employee needs it to plan leave. Writing is HR/Admin only.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.core.deps import CurrentUser, DbSession, HrUser
from app.core.errors import ConflictError, NotFoundError
from app.models.enums import AuditAction
from app.models.holiday import Holiday
from app.schemas.common import Message
from app.schemas.holiday import (
    HolidayCreate,
    HolidayRead,
    HolidayUpdate,
    HolidayYearSummary,
)
from app.services.audit import record_audit
from app.services.holidays import (
    find_clash,
    list_holidays,
    to_read,
    today,
    year_summary,
)

router = APIRouter(prefix="/holidays", tags=["Holiday Calendar"])


def _get_or_404(db: DbSession, holiday_id: uuid.UUID) -> Holiday:
    holiday = db.get(Holiday, holiday_id)
    if holiday is None:
        raise NotFoundError("Holiday not found.")
    return holiday


@router.get("", response_model=list[HolidayRead], summary="List holidays")
def list_all(
    db: DbSession,
    user: CurrentUser,
    year: Annotated[int | None, Query(ge=1970, le=2200)] = None,
    include_inactive: bool = False,
) -> list[HolidayRead]:
    """Holidays for a year, earliest first. Defaults to the current year.

    Only HR/Admin may see soft-deleted rows; an employee asking for them gets
    the active list rather than an error, since it is a display concern.
    """
    year = year if year is not None else today().year
    may_see_inactive = include_inactive and user.role.value in {"admin", "hr"}
    rows = list_holidays(db, year=year, include_inactive=may_see_inactive)
    reference = today()
    return [to_read(row, reference=reference) for row in rows]


@router.get("/summary", response_model=HolidayYearSummary, summary="Year summary")
def summary(
    db: DbSession,
    _: CurrentUser,
    year: Annotated[int | None, Query(ge=1970, le=2200)] = None,
) -> HolidayYearSummary:
    return year_summary(db, year=year if year is not None else today().year)


@router.post(
    "",
    response_model=HolidayRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a holiday",
)
def create(
    db: DbSession,
    user: HrUser,
    payload: HolidayCreate,
    request: Request,
) -> HolidayRead:
    if find_clash(db, holiday_date=payload.holiday_date, name=payload.name):
        raise ConflictError(
            f"{payload.name} is already on the calendar for {payload.holiday_date}."
        )

    holiday = Holiday(
        name=payload.name,
        holiday_date=payload.holiday_date,
        type=payload.type,
        description=payload.description,
        created_by_id=user.id,
    )
    db.add(holiday)
    db.flush()

    record_audit(
        db,
        action=AuditAction.HOLIDAY_CREATED,
        actor=user,
        entity_type="holiday",
        entity_id=holiday.id,
        detail={"name": holiday.name, "date": holiday.holiday_date.isoformat()},
        request=request,
    )
    db.commit()
    db.refresh(holiday)
    return to_read(holiday)


@router.patch("/{holiday_id}", response_model=HolidayRead, summary="Edit a holiday")
def update(
    db: DbSession,
    user: HrUser,
    holiday_id: uuid.UUID,
    payload: HolidayUpdate,
    request: Request,
) -> HolidayRead:
    holiday = _get_or_404(db, holiday_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        return to_read(holiday)

    # The clash check needs the post-edit values, which may come from either
    # the payload or the untouched row.
    new_date = changes.get("holiday_date", holiday.holiday_date)
    new_name = changes.get("name", holiday.name)
    if ("holiday_date" in changes or "name" in changes) and find_clash(
        db, holiday_date=new_date, name=new_name, exclude_id=holiday.id
    ):
        raise ConflictError(f"{new_name} is already on the calendar for {new_date}.")

    for field, value in changes.items():
        setattr(holiday, field, value)

    record_audit(
        db,
        action=AuditAction.HOLIDAY_UPDATED,
        actor=user,
        entity_type="holiday",
        entity_id=holiday.id,
        detail={"changed": sorted(changes)},
        request=request,
    )
    db.commit()
    db.refresh(holiday)
    return to_read(holiday)


@router.delete("/{holiday_id}", response_model=Message, summary="Remove a holiday")
def remove(
    db: DbSession,
    user: HrUser,
    holiday_id: uuid.UUID,
    request: Request,
) -> Message:
    """Soft delete. The row stays so past calendars remain intact."""
    holiday = _get_or_404(db, holiday_id)
    if not holiday.is_active:
        raise ConflictError("That holiday has already been removed.")

    holiday.is_active = False
    record_audit(
        db,
        action=AuditAction.HOLIDAY_DELETED,
        actor=user,
        entity_type="holiday",
        entity_id=holiday.id,
        detail={"name": holiday.name, "date": holiday.holiday_date.isoformat()},
        request=request,
    )
    db.commit()
    return Message(message=f"{holiday.name} removed from the calendar.")
