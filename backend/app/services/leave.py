"""Leave entitlements, balances and the deduction ledger.

Entitlements are the handbook's, not invented here:

  Annual — 21 days per calendar year, accruing at 1.75 days per completed
           month, pro-rated for anyone who joins part-way through the year.
           Up to 10 unused days carry forward.
  Sick   — 12 days per calendar year. No carry-forward, no encashment.
  Unpaid — no balance; always available.

Keeping these in step with the Annual Leave Policy and Sick Leave documents
matters because the assistant quotes those documents. An employee who is told
"21 days" and then sees a different number has been given two answers by one
system.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationError
from app.core.security import today_utc
from app.models.employee import Employee
from app.models.enums import LeaveKind, RequestStatus, RequestType
from app.models.leave import LeaveBalance
from app.models.request import Request

# --- Policy ------------------------------------------------------------------

ANNUAL_DAYS_PER_YEAR = Decimal("21")
ANNUAL_ACCRUAL_PER_MONTH = Decimal("1.75")  # 21 / 12
SICK_DAYS_PER_YEAR = Decimal("12")
MAX_CARRY_FORWARD = Decimal("10")

ENTITLEMENT = {
    LeaveKind.ANNUAL: ANNUAL_DAYS_PER_YEAR,
    LeaveKind.SICK: SICK_DAYS_PER_YEAR,
}

# Kinds that draw down a balance, in display order.
TRACKED_KINDS = (LeaveKind.ANNUAL, LeaveKind.SICK)


def _quantise(value: Decimal) -> Decimal:
    """Round to the half-day that is actually bookable.

    ROUND_HALF_UP, not Decimal's default banker's rounding. Accrual lands on an
    exact half often — 1.75 a month means a tie every odd number of months —
    and on a tie the employee should get the larger number. Banker's rounding
    would also make the result depend on whether the neighbour is even, which
    is impossible to explain to someone querying their balance.
    """
    return (value * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2


def entitlement_for(kind: LeaveKind, *, year: int, joined: date | None) -> Decimal:
    """This year's allowance, pro-rated for a mid-year joiner.

    Someone who joins in October has not earned a full year of leave, and
    granting it would let them take more than they accrue. Months are counted
    from the joining month inclusive, matching "per completed month of service"
    read generously in the employee's favour — the alternative rounds a joiner
    down for a month they largely worked.
    """
    if kind is LeaveKind.UNPAID:
        return Decimal("0")

    full = ENTITLEMENT[kind]
    if joined is None or joined.year < year:
        return full
    if joined.year > year:
        return Decimal("0")

    months_remaining = 12 - joined.month + 1
    if kind is LeaveKind.ANNUAL:
        return _quantise(min(full, ANNUAL_ACCRUAL_PER_MONTH * months_remaining))
    return _quantise(full * Decimal(months_remaining) / 12)


def carry_forward_for(
    db: Session, *, employee_id: uuid.UUID, kind: LeaveKind, year: int
) -> Decimal:
    """Unused days brought in from last year, capped by policy.

    Annual only: the Sick Leave document says sick leave does not carry
    forward, so it is not silently treated the same way.
    """
    if kind is not LeaveKind.ANNUAL:
        return Decimal("0")

    previous = db.scalar(
        select(LeaveBalance).where(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.year == year - 1,
            LeaveBalance.leave_kind == kind,
        )
    )
    if previous is None:
        return Decimal("0")
    return max(Decimal("0"), min(MAX_CARRY_FORWARD, previous.available_days))


# --- Balances ----------------------------------------------------------------


def get_or_create_balance(
    db: Session, *, employee: Employee, kind: LeaveKind, year: int | None = None
) -> LeaveBalance:
    """The balance row for this period, created on first use.

    Created lazily rather than by a year-start batch job: there is no scheduler
    in this build, and a missing row would otherwise read as a zero balance —
    silently blocking every request instead of failing visibly.
    """
    year = year if year is not None else today_utc().year
    existing = db.scalar(
        select(LeaveBalance).where(
            LeaveBalance.employee_id == employee.id,
            LeaveBalance.year == year,
            LeaveBalance.leave_kind == kind,
        )
    )
    if existing is not None:
        return existing

    balance = LeaveBalance(
        employee_id=employee.id,
        year=year,
        leave_kind=kind,
        entitled_days=entitlement_for(kind, year=year, joined=employee.date_of_joining),
        carried_forward_days=carry_forward_for(
            db, employee_id=employee.id, kind=kind, year=year
        ),
        used_days=Decimal("0"),
    )
    db.add(balance)
    db.flush()
    return balance


def balances_for(
    db: Session, *, employee: Employee, year: int | None = None
) -> list[LeaveBalance]:
    """Every tracked balance for the year, in display order."""
    year = year if year is not None else today_utc().year
    return [
        get_or_create_balance(db, employee=employee, kind=kind, year=year)
        for kind in TRACKED_KINDS
    ]


# --- The ledger --------------------------------------------------------------


def check_available(
    db: Session, *, employee: Employee, kind: LeaveKind, days: Decimal, year: int
) -> None:
    """Refuse a request that exceeds what is left, naming both numbers.

    Called at submission and again at approval. Between the two, another
    request can be approved and consume the same days — checking only at
    submission would let a balance go negative through no one's mistake.
    """
    if not kind.is_paid:
        return

    balance = get_or_create_balance(db, employee=employee, kind=kind, year=year)
    if days > balance.available_days:
        raise ValidationError(
            f"That request needs {days:g} day(s) of {kind.value} leave but only "
            f"{balance.available_days:g} remain for {year}. Unpaid leave is "
            f"always available if the paid balance is exhausted."
        )


def deduct(
    db: Session, *, employee: Employee, kind: LeaveKind, days: Decimal, year: int
) -> LeaveBalance | None:
    """Draw days down. Returns None for kinds that carry no balance."""
    if not kind.is_paid:
        return None
    balance = get_or_create_balance(db, employee=employee, kind=kind, year=year)
    balance.used_days = balance.used_days + days
    return balance


def restore(
    db: Session, *, employee: Employee, kind: LeaveKind, days: Decimal, year: int
) -> LeaveBalance | None:
    """Give days back when an approved request stops counting.

    Clamped at zero: a balance that has gone negative is a bug, and restoring
    past zero would hide it behind a plausible-looking number.
    """
    if not kind.is_paid:
        return None
    balance = get_or_create_balance(db, employee=employee, kind=kind, year=year)
    balance.used_days = max(Decimal("0"), balance.used_days - days)
    return balance


def recompute_used_days(
    db: Session, *, employee: Employee, year: int | None = None
) -> dict[LeaveKind, Decimal]:
    """Rebuild used_days from the approved requests themselves.

    The stored counter exists so balance display costs one row read instead of
    a scan. This is how that counter is proved right — and how it would be
    repaired if a future code path forgot to call deduct().
    """
    year = year if year is not None else today_utc().year
    approved = db.scalars(
        select(Request).where(
            Request.employee_id == employee.id,
            Request.type == RequestType.LEAVE,
            Request.status == RequestStatus.APPROVED,
        )
    ).unique()

    # The payload is re-parsed rather than read key by key. `days` is derived
    # from the dates, so it is not a stored field — reading payload["days"]
    # returns nothing and silently reconciles every balance to zero.
    from app.services.requests import validate_payload

    totals: dict[LeaveKind, Decimal] = {kind: Decimal("0") for kind in TRACKED_KINDS}
    for request in approved:
        try:
            payload = validate_payload(request.type, request.payload or {})
        except Exception:  # noqa: BLE001 - a malformed row must not stop the rebuild
            continue
        kind = payload.kind
        if not kind.is_paid or payload.start_date.year != year:
            continue
        totals[kind] = totals[kind] + Decimal(str(payload.days))

    for kind, total in totals.items():
        balance = get_or_create_balance(db, employee=employee, kind=kind, year=year)
        balance.used_days = total
    return totals
