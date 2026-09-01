"""Leave: entitlement maths, the balance ledger, and the deduction lifecycle.

The entitlements here are the handbook's — 21 days annual accruing at 1.75 a
month, 12 sick, 10 carried forward at most — because the assistant quotes those
documents. A number that drifts from them means one system giving an employee
two answers, so the policy constants are asserted directly rather than only
through behaviour.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import ValidationError
from app.core.security import today_utc
from app.models.employee import Employee
from app.models.enums import LeaveKind, UserRole
from app.models.leave import LeaveBalance
from app.models.user import User
from app.services.leave import (
    ANNUAL_DAYS_PER_YEAR,
    MAX_CARRY_FORWARD,
    SICK_DAYS_PER_YEAR,
    balances_for,
    carry_forward_for,
    check_available,
    deduct,
    entitlement_for,
    get_or_create_balance,
    recompute_used_days,
    restore,
)
from tests.conftest import API, _make_user, auth_headers

EMPLOYEE = {"email": "leave.taker@example.com", "password": "Leave@12345"}


def _employee(db, *, joined: date | None = date(2025, 1, 6), code: str = "EMP7001") -> Employee:
    employee = Employee(
        employee_code=code,
        first_name="Asha",
        last_name="Rao",
        work_email=f"{code.lower()}@example.com",
        date_of_joining=joined,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


# --- The policy constants ----------------------------------------------------


def test_entitlements_match_the_handbook():
    """These are quoted verbatim by the assistant from the knowledge base."""
    assert ANNUAL_DAYS_PER_YEAR == Decimal("21")
    assert SICK_DAYS_PER_YEAR == Decimal("12")
    assert MAX_CARRY_FORWARD == Decimal("10")


# --- Entitlement and pro-rating ---------------------------------------------


def test_an_employee_who_joined_earlier_gets_the_full_year():
    assert entitlement_for(LeaveKind.ANNUAL, year=2026, joined=date(2024, 5, 1)) == Decimal("21")
    assert entitlement_for(LeaveKind.SICK, year=2026, joined=date(2024, 5, 1)) == Decimal("12")


def test_a_january_joiner_gets_the_full_year():
    """Twelve months of accrual is the whole entitlement; it must not exceed it."""
    assert entitlement_for(LeaveKind.ANNUAL, year=2026, joined=date(2026, 1, 20)) == Decimal("21")


@pytest.mark.parametrize(
    "join_month,expected_annual",
    [(1, "21"), (4, "16"), (7, "10.5"), (10, "5.5"), (12, "2")],
)
def test_a_mid_year_joiner_is_pro_rated(join_month, expected_annual):
    """1.75 days per remaining month, so nobody can take leave they never accrued.

    Accrual lands on an exact half-day every odd number of months (1.75, 5.25,
    8.75...). Those tie-break upward, in the employee's favour.
    """
    got = entitlement_for(LeaveKind.ANNUAL, year=2026, joined=date(2026, join_month, 15))
    assert got == Decimal(expected_annual)


def test_someone_who_has_not_joined_yet_has_no_entitlement():
    assert entitlement_for(LeaveKind.ANNUAL, year=2026, joined=date(2027, 2, 1)) == Decimal("0")


def test_unpaid_leave_has_no_entitlement_because_it_needs_none():
    assert entitlement_for(LeaveKind.UNPAID, year=2026, joined=date(2020, 1, 1)) == Decimal("0")
    assert LeaveKind.UNPAID.is_paid is False


# --- Carry forward -----------------------------------------------------------


def test_unused_annual_leave_carries_forward_up_to_the_cap(db):
    employee = _employee(db)
    previous = get_or_create_balance(db, employee=employee, kind=LeaveKind.ANNUAL, year=2025)
    previous.used_days = Decimal("4")  # 21 - 4 = 17 unused, capped at 10
    db.commit()

    assert carry_forward_for(
        db, employee_id=employee.id, kind=LeaveKind.ANNUAL, year=2026
    ) == Decimal("10")


def test_carry_forward_is_the_unused_amount_when_under_the_cap(db):
    employee = _employee(db)
    previous = get_or_create_balance(db, employee=employee, kind=LeaveKind.ANNUAL, year=2025)
    previous.used_days = Decimal("18")  # 3 unused
    db.commit()

    assert carry_forward_for(
        db, employee_id=employee.id, kind=LeaveKind.ANNUAL, year=2026
    ) == Decimal("3")


def test_sick_leave_does_not_carry_forward(db):
    """The handbook says so explicitly; treating it like annual would over-grant."""
    employee = _employee(db)
    get_or_create_balance(db, employee=employee, kind=LeaveKind.SICK, year=2025)
    db.commit()

    assert carry_forward_for(
        db, employee_id=employee.id, kind=LeaveKind.SICK, year=2026
    ) == Decimal("0")


def test_the_first_year_carries_nothing_forward(db):
    employee = _employee(db)
    assert carry_forward_for(
        db, employee_id=employee.id, kind=LeaveKind.ANNUAL, year=2026
    ) == Decimal("0")


def test_a_new_years_balance_includes_what_was_carried_in(db):
    employee = _employee(db)
    previous = get_or_create_balance(db, employee=employee, kind=LeaveKind.ANNUAL, year=2025)
    previous.used_days = Decimal("15")  # 6 unused
    db.commit()

    current = get_or_create_balance(db, employee=employee, kind=LeaveKind.ANNUAL, year=2026)
    assert current.carried_forward_days == Decimal("6")
    assert current.total_days == Decimal("27")
    assert current.available_days == Decimal("27")


# --- The ledger --------------------------------------------------------------


def test_balances_are_created_on_first_read_not_by_a_batch_job(db):
    """No scheduler exists; a missing row would read as a zero balance."""
    employee = _employee(db)
    assert db.scalar(select(LeaveBalance).where(LeaveBalance.employee_id == employee.id)) is None

    rows = balances_for(db, employee=employee, year=2026)
    db.commit()
    assert {r.leave_kind for r in rows} == {LeaveKind.ANNUAL, LeaveKind.SICK}


def test_deducting_reduces_what_is_available(db):
    employee = _employee(db)
    balance = deduct(db, employee=employee, kind=LeaveKind.ANNUAL, days=Decimal("3"), year=2026)
    db.commit()
    assert balance.used_days == Decimal("3")
    assert balance.available_days == Decimal("18")


def test_half_days_stay_exact_across_many_operations(db):
    """Numeric, not float: 0.5 added and removed repeatedly must not drift."""
    employee = _employee(db)
    for _ in range(10):
        deduct(db, employee=employee, kind=LeaveKind.ANNUAL, days=Decimal("0.5"), year=2026)
    db.commit()
    balance = get_or_create_balance(db, employee=employee, kind=LeaveKind.ANNUAL, year=2026)
    assert balance.used_days == Decimal("5.0")
    assert balance.available_days == Decimal("16.0")


def test_restoring_gives_the_days_back(db):
    employee = _employee(db)
    deduct(db, employee=employee, kind=LeaveKind.ANNUAL, days=Decimal("4"), year=2026)
    restore(db, employee=employee, kind=LeaveKind.ANNUAL, days=Decimal("4"), year=2026)
    db.commit()
    balance = get_or_create_balance(db, employee=employee, kind=LeaveKind.ANNUAL, year=2026)
    assert balance.used_days == Decimal("0")


def test_restoring_cannot_drive_used_days_negative(db):
    """A negative balance is a bug; hiding it behind a plausible number is worse."""
    employee = _employee(db)
    restore(db, employee=employee, kind=LeaveKind.ANNUAL, days=Decimal("5"), year=2026)
    db.commit()
    balance = get_or_create_balance(db, employee=employee, kind=LeaveKind.ANNUAL, year=2026)
    assert balance.used_days == Decimal("0")


def test_unpaid_leave_touches_no_balance(db):
    employee = _employee(db)
    assert deduct(db, employee=employee, kind=LeaveKind.UNPAID, days=Decimal("5"), year=2026) is None
    check_available(db, employee=employee, kind=LeaveKind.UNPAID, days=Decimal("999"), year=2026)


def test_requesting_more_than_remains_is_refused_with_both_numbers(db):
    employee = _employee(db)
    deduct(db, employee=employee, kind=LeaveKind.ANNUAL, days=Decimal("19"), year=2026)
    db.commit()

    with pytest.raises(ValidationError) as caught:
        check_available(
            db, employee=employee, kind=LeaveKind.ANNUAL, days=Decimal("5"), year=2026
        )
    message = str(caught.value)
    assert "5" in message and "2" in message
    assert "unpaid" in message.lower()  # names the way forward


def test_using_exactly_the_remaining_balance_is_allowed(db):
    """The boundary: 21 of 21 is not "more than available"."""
    employee = _employee(db)
    check_available(db, employee=employee, kind=LeaveKind.ANNUAL, days=Decimal("21"), year=2026)


# --- The full lifecycle, through the API ------------------------------------


@pytest.fixture
def leave_ctx(client, db):
    """An employee with a login, joined long enough ago for a full entitlement."""
    user = _make_user(
        db, email=EMPLOYEE["email"], password=EMPLOYEE["password"], role=UserRole.EMPLOYEE
    )
    employee = Employee(
        employee_code="EMP7100",
        user_id=user.id,
        first_name="Asha",
        last_name="Rao",
        work_email=EMPLOYEE["email"],
        date_of_joining=date(2024, 3, 1),
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return {
        "user": user,
        "employee": employee,
        "headers": auth_headers(client, EMPLOYEE["email"], EMPLOYEE["password"]),
    }


def _apply(client, headers, *, kind="annual", start=None, end=None, **extra):
    start = start or (today_utc() + timedelta(days=30))
    end = end or start
    body = {
        "type": "leave",
        "payload": {
            "leave_kind": kind,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "reason": "Family wedding",
            **extra,
        },
    }
    return client.post(f"{API}/my-requests", json=body, headers=headers)


def _balance(client, headers, kind="annual"):
    body = client.get(f"{API}/my-leave-balance", headers=headers).json()
    return next(b for b in body["balances"] if b["leave_kind"] == kind)


def test_the_balance_endpoint_reports_the_handbook_entitlement(client, leave_ctx):
    body = client.get(f"{API}/my-leave-balance", headers=leave_ctx["headers"]).json()
    assert body["year"] == today_utc().year
    assert body["unpaid_always_available"] is True

    annual = next(b for b in body["balances"] if b["leave_kind"] == "annual")
    sick = next(b for b in body["balances"] if b["leave_kind"] == "sick")
    assert (annual["entitled_days"], annual["available_days"]) == (21.0, 21.0)
    assert (sick["entitled_days"], sick["available_days"]) == (12.0, 12.0)


def test_submitting_does_not_deduct_anything(client, leave_ctx):
    """Only an approval consumes the balance; a pending request is a request."""
    start = today_utc() + timedelta(days=30)
    assert _apply(client, leave_ctx["headers"], start=start, end=start + timedelta(days=2)).status_code == 201
    assert _balance(client, leave_ctx["headers"])["available_days"] == 21.0


def test_approval_deducts_the_days(client, leave_ctx, hr_headers):
    start = today_utc() + timedelta(days=30)
    created = _apply(client, leave_ctx["headers"], start=start, end=start + timedelta(days=2)).json()

    approved = client.post(
        f"{API}/requests/{created['id']}/approve", json={}, headers=hr_headers
    )
    assert approved.status_code == 200, approved.text

    balance = _balance(client, leave_ctx["headers"])
    assert balance["used_days"] == 3.0
    assert balance["available_days"] == 18.0


def test_a_rejection_deducts_nothing(client, leave_ctx, hr_headers):
    start = today_utc() + timedelta(days=30)
    created = _apply(client, leave_ctx["headers"], start=start, end=start + timedelta(days=4)).json()
    client.post(
        f"{API}/requests/{created['id']}/reject", json={"note": "Short-staffed"}, headers=hr_headers
    )
    assert _balance(client, leave_ctx["headers"])["available_days"] == 21.0


def test_a_half_day_deducts_half_a_day(client, leave_ctx, hr_headers):
    start = today_utc() + timedelta(days=30)
    created = _apply(
        client, leave_ctx["headers"], start=start, end=start, half_day=True
    ).json()
    client.post(f"{API}/requests/{created['id']}/approve", json={}, headers=hr_headers)
    assert _balance(client, leave_ctx["headers"])["used_days"] == 0.5


def test_submitting_beyond_the_balance_is_refused(client, leave_ctx):
    start = today_utc() + timedelta(days=30)
    response = _apply(
        client, leave_ctx["headers"], start=start, end=start + timedelta(days=40)
    )
    assert response.status_code == 422
    message = response.json()["error"]["message"]
    assert "41" in message and "21" in message


def test_unpaid_leave_is_available_past_the_paid_balance(client, leave_ctx, hr_headers):
    """The escape hatch the refusal message points at must actually work."""
    start = today_utc() + timedelta(days=30)
    response = _apply(
        client, leave_ctx["headers"], kind="unpaid", start=start, end=start + timedelta(days=40)
    )
    assert response.status_code == 201
    approved = client.post(
        f"{API}/requests/{response.json()['id']}/approve", json={}, headers=hr_headers
    )
    assert approved.status_code == 200
    assert _balance(client, leave_ctx["headers"])["available_days"] == 21.0


def test_a_second_approval_cannot_overdraw_the_balance(client, leave_ctx, hr_headers):
    """Two requests submitted while both fit, approved when only one does.

    Checking only at submission would let the balance go negative through
    nobody's mistake, so approval re-checks.
    """
    start = today_utc() + timedelta(days=30)
    first = _apply(client, leave_ctx["headers"], start=start, end=start + timedelta(days=14)).json()
    second = _apply(
        client,
        leave_ctx["headers"],
        start=start + timedelta(days=60),
        end=start + timedelta(days=74),
    ).json()

    assert client.post(
        f"{API}/requests/{first['id']}/approve", json={}, headers=hr_headers
    ).status_code == 200

    blocked = client.post(f"{API}/requests/{second['id']}/approve", json={}, headers=hr_headers)
    assert blocked.status_code == 422
    assert _balance(client, leave_ctx["headers"])["used_days"] == 15.0


def test_withdrawing_approved_future_leave_gives_the_days_back(client, leave_ctx, hr_headers):
    start = today_utc() + timedelta(days=30)
    created = _apply(client, leave_ctx["headers"], start=start, end=start + timedelta(days=2)).json()
    client.post(f"{API}/requests/{created['id']}/approve", json={}, headers=hr_headers)
    assert _balance(client, leave_ctx["headers"])["used_days"] == 3.0

    cancelled = client.post(
        f"{API}/my-requests/{created['id']}/cancel", headers=leave_ctx["headers"]
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert _balance(client, leave_ctx["headers"])["used_days"] == 0.0


def test_leave_that_has_already_started_cannot_be_withdrawn(client, db, leave_ctx, hr_headers):
    """Reversing leave someone is already taking is HR's job, not a self-service button."""
    from app.models.request import Request

    start = today_utc() + timedelta(days=30)
    created = _apply(client, leave_ctx["headers"], start=start, end=start + timedelta(days=2)).json()
    client.post(f"{API}/requests/{created['id']}/approve", json={}, headers=hr_headers)

    # Move it into the past without going through the API.
    row = db.get(Request, __import__("uuid").UUID(created["id"]))
    payload = dict(row.payload)
    payload["start_date"] = (today_utc() - timedelta(days=1)).isoformat()
    row.payload = payload
    db.commit()

    blocked = client.post(
        f"{API}/my-requests/{created['id']}/cancel", headers=leave_ctx["headers"]
    )
    assert blocked.status_code == 409
    assert "already started" in blocked.json()["error"]["message"]


def test_the_stored_counter_matches_what_the_requests_say(client, db, leave_ctx, hr_headers):
    """used_days is a cached figure; this is the proof it cannot drift.

    A mixed sequence — approved, rejected, approved-then-withdrawn, pending —
    then recompute from the requests themselves and compare.
    """
    start = today_utc() + timedelta(days=30)
    approved = _apply(client, leave_ctx["headers"], start=start, end=start + timedelta(days=2)).json()
    rejected = _apply(client, leave_ctx["headers"], start=start + timedelta(days=10),
                      end=start + timedelta(days=12)).json()
    withdrawn = _apply(client, leave_ctx["headers"], start=start + timedelta(days=20),
                       end=start + timedelta(days=21)).json()
    _apply(client, leave_ctx["headers"], start=start + timedelta(days=30),
           end=start + timedelta(days=31))  # left pending

    client.post(f"{API}/requests/{approved['id']}/approve", json={}, headers=hr_headers)
    client.post(f"{API}/requests/{rejected['id']}/reject", json={"note": "no"}, headers=hr_headers)
    client.post(f"{API}/requests/{withdrawn['id']}/approve", json={}, headers=hr_headers)
    client.post(f"{API}/my-requests/{withdrawn['id']}/cancel", headers=leave_ctx["headers"])

    stored = _balance(client, leave_ctx["headers"])["used_days"]
    assert stored == 3.0  # only the one still approved

    db.expire_all()
    employee = db.get(Employee, leave_ctx["employee"].id)
    derived = recompute_used_days(db, employee=employee, year=today_utc().year)
    db.commit()
    assert float(derived[LeaveKind.ANNUAL]) == stored


def test_an_employee_without_a_record_gets_a_clear_404(client, db):
    _make_user(db, email="norecord@example.com", password="NoRec@12345", role=UserRole.EMPLOYEE)
    headers = auth_headers(client, "norecord@example.com", "NoRec@12345")
    assert client.get(f"{API}/my-leave-balance", headers=headers).status_code == 404


def test_the_balance_is_private_to_its_owner(client, db, leave_ctx):
    """There is no route that returns someone else's balance."""
    other = _make_user(db, email="nosy@example.com", password="Nosy@12345", role=UserRole.EMPLOYEE)
    employee = Employee(
        employee_code="EMP7200", user_id=other.id, first_name="Nosy", last_name="Person",
        work_email="nosy@example.com", date_of_joining=date(2024, 1, 1),
    )
    db.add(employee)
    db.commit()

    headers = auth_headers(client, "nosy@example.com", "Nosy@12345")
    body = client.get(f"{API}/my-leave-balance", headers=headers).json()
    # Their own, untouched balance — not the other employee's.
    assert all(b["used_days"] == 0.0 for b in body["balances"])


def test_can_cancel_matches_what_the_endpoint_will_actually_accept(
    client, db, leave_ctx, hr_headers
):
    """The flag the UI reads must agree with the rule cancel() enforces.

    These drifted once: the API accepted withdrawal of approved future leave
    while the row reported can_cancel=False, so the button never rendered and
    the feature was unreachable from the product. Backend tests missed it
    because they call the endpoint directly.
    """
    from app.models.request import Request

    start = today_utc() + timedelta(days=30)
    created = _apply(client, leave_ctx["headers"], start=start, end=start + timedelta(days=2)).json()
    assert created["can_cancel"] is True  # pending

    approved = client.post(
        f"{API}/requests/{created['id']}/approve", json={}, headers=hr_headers
    ).json()
    assert approved["can_cancel"] is False  # HR's view: not their request

    mine = client.get(f"{API}/my-requests", headers=leave_ctx["headers"]).json()[0]
    assert mine["status"] == "approved"
    assert mine["can_cancel"] is True, "approved future leave is withdrawable"

    # Once it has started the flag must flip, in step with the endpoint.
    row = db.get(Request, __import__("uuid").UUID(created["id"]))
    payload = dict(row.payload)
    payload["start_date"] = (today_utc() - timedelta(days=1)).isoformat()
    row.payload = payload
    db.commit()

    started = client.get(f"{API}/my-requests", headers=leave_ctx["headers"]).json()[0]
    assert started["can_cancel"] is False
    assert client.post(
        f"{API}/my-requests/{created['id']}/cancel", headers=leave_ctx["headers"]
    ).status_code == 409


def test_a_withdrawal_is_attributed_to_whoever_withdrew_it(client, leave_ctx, hr_headers):
    """Not to whoever approved it earlier.

    decided_by_id was set by the approval and left untouched by the
    withdrawal, so the UI read "Withdrawn by <the HR approver>" for an action
    the employee took themselves.
    """
    start = today_utc() + timedelta(days=30)
    created = _apply(client, leave_ctx["headers"], start=start, end=start + timedelta(days=2)).json()
    client.post(f"{API}/requests/{created['id']}/approve", json={}, headers=hr_headers)

    cancelled = client.post(
        f"{API}/my-requests/{created['id']}/cancel", headers=leave_ctx["headers"]
    ).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["decided_by_name"] == leave_ctx["user"].full_name
