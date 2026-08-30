"""Holiday calendar: access rules, the date maths the UI relies on, and soft delete."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.enums import UserRole
from app.services.holidays import today
from tests.conftest import API, _make_user, auth_headers

EMPLOYEE = {"email": "employee@example.com", "password": "EmployeePass123!"}


@pytest.fixture
def employee_headers(client: TestClient, db: Session) -> dict[str, str]:
    _make_user(db, email=EMPLOYEE["email"], password=EMPLOYEE["password"], role=UserRole.EMPLOYEE)
    return auth_headers(client, EMPLOYEE["email"], EMPLOYEE["password"])


def _create(client: TestClient, headers: dict, **overrides) -> dict:
    payload = {
        "name": "Diwali",
        "holiday_date": "2026-11-08",
        "type": "public",
    } | overrides
    response = client.post(f"{API}/holidays", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# --- Access ------------------------------------------------------------------


def test_every_signed_in_role_can_read_the_calendar(client, hr_headers, employee_headers):
    """The calendar is company-wide information; an employee needs it to plan leave."""
    _create(client, hr_headers)
    response = client.get(f"{API}/holidays", params={"year": 2026}, headers=employee_headers)
    assert response.status_code == 200
    assert [h["name"] for h in response.json()] == ["Diwali"]


def test_an_employee_cannot_change_the_calendar(client, hr_headers, employee_headers):
    created = _create(client, hr_headers)
    assert client.post(
        f"{API}/holidays",
        json={"name": "Fake", "holiday_date": "2026-12-25", "type": "public"},
        headers=employee_headers,
    ).status_code == 403
    assert client.patch(
        f"{API}/holidays/{created['id']}", json={"name": "Edited"}, headers=employee_headers
    ).status_code == 403
    assert client.delete(
        f"{API}/holidays/{created['id']}", headers=employee_headers
    ).status_code == 403


def test_the_calendar_is_not_readable_when_signed_out(client):
    assert client.get(f"{API}/holidays").status_code == 401


# --- Derived fields ----------------------------------------------------------


def test_upcoming_and_past_holidays_are_labelled_from_the_server(client, hr_headers):
    """days_until/is_past are computed server-side so clients cannot disagree on 'today'."""
    reference = today()
    future = reference + timedelta(days=10)
    past = reference - timedelta(days=10)

    _create(client, hr_headers, name="Future Day", holiday_date=future.isoformat())
    _create(client, hr_headers, name="Past Day", holiday_date=past.isoformat())
    _create(client, hr_headers, name="Today Off", holiday_date=reference.isoformat())

    rows = {h["name"]: h for h in client.get(
        f"{API}/holidays", params={"year": reference.year}, headers=hr_headers
    ).json()}

    assert rows["Future Day"]["days_until"] == 10
    assert rows["Future Day"]["is_past"] is False
    assert rows["Today Off"]["days_until"] == 0  # today is not yet past
    assert rows["Today Off"]["is_past"] is False
    assert rows["Past Day"]["is_past"] is True
    assert rows["Past Day"]["days_until"] is None


def test_weekday_is_reported_for_the_date(client, hr_headers):
    created = _create(client, hr_headers, holiday_date="2026-11-08")  # a Sunday
    assert created["weekday"] == "Sunday"


def test_holidays_come_back_in_date_order(client, hr_headers):
    _create(client, hr_headers, name="Christmas", holiday_date="2026-12-25")
    _create(client, hr_headers, name="Republic Day", holiday_date="2026-01-26")
    _create(client, hr_headers, name="Diwali", holiday_date="2026-11-08")

    names = [h["name"] for h in client.get(
        f"{API}/holidays", params={"year": 2026}, headers=hr_headers
    ).json()]
    assert names == ["Republic Day", "Diwali", "Christmas"]


# --- Filtering ---------------------------------------------------------------


def test_a_year_filter_excludes_other_years(client, hr_headers):
    _create(client, hr_headers, name="NY 2026", holiday_date="2026-01-01")
    _create(client, hr_headers, name="NY 2027", holiday_date="2027-01-01")

    for year, expected in ((2026, ["NY 2026"]), (2027, ["NY 2027"])):
        rows = client.get(f"{API}/holidays", params={"year": year}, headers=hr_headers).json()
        assert [h["name"] for h in rows] == expected


def test_year_boundaries_are_inclusive(client, hr_headers):
    """Dec 31 and Jan 1 belong to their own year — an off-by-one here loses holidays."""
    _create(client, hr_headers, name="Last Day", holiday_date="2026-12-31")
    _create(client, hr_headers, name="First Day", holiday_date="2026-01-01")
    rows = client.get(f"{API}/holidays", params={"year": 2026}, headers=hr_headers).json()
    assert {h["name"] for h in rows} == {"First Day", "Last Day"}


# --- Duplicates --------------------------------------------------------------


def test_the_same_holiday_twice_on_one_date_is_rejected(client, hr_headers):
    _create(client, hr_headers)
    response = client.post(
        f"{API}/holidays",
        json={"name": "Diwali", "holiday_date": "2026-11-08", "type": "public"},
        headers=hr_headers,
    )
    assert response.status_code == 409
    assert "already on the calendar" in response.json()["error"]["message"]


def test_duplicate_detection_ignores_case_and_padding(client, hr_headers):
    """'  diwali ' must not slip past the check and create a near-duplicate row."""
    _create(client, hr_headers)
    response = client.post(
        f"{API}/holidays",
        json={"name": "  diwali ", "holiday_date": "2026-11-08", "type": "public"},
        headers=hr_headers,
    )
    assert response.status_code == 409


def test_two_different_holidays_may_share_a_date(client, hr_headers):
    """Festivals do collide; the constraint is (date, name), not date alone."""
    _create(client, hr_headers, name="Diwali", holiday_date="2026-11-08")
    _create(client, hr_headers, name="Founders Day", holiday_date="2026-11-08")


def test_editing_onto_an_occupied_date_and_name_is_rejected(client, hr_headers):
    _create(client, hr_headers, name="Diwali", holiday_date="2026-11-08")
    other = _create(client, hr_headers, name="Holi", holiday_date="2026-03-04")

    response = client.patch(
        f"{API}/holidays/{other['id']}",
        json={"name": "Diwali", "holiday_date": "2026-11-08"},
        headers=hr_headers,
    )
    assert response.status_code == 409


def test_editing_a_holiday_without_moving_it_is_allowed(client, hr_headers):
    """The clash check must exclude the row being edited, or every edit 409s."""
    created = _create(client, hr_headers)
    response = client.patch(
        f"{API}/holidays/{created['id']}",
        json={"holiday_date": "2026-11-08", "description": "Festival of lights"},
        headers=hr_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["description"] == "Festival of lights"


# --- Editing and removal -----------------------------------------------------


def test_a_partial_edit_leaves_other_fields_alone(client, hr_headers):
    created = _create(client, hr_headers, description="Original")
    updated = client.patch(
        f"{API}/holidays/{created['id']}", json={"type": "company"}, headers=hr_headers
    ).json()
    assert updated["type"] == "company"
    assert updated["description"] == "Original"
    assert updated["name"] == "Diwali"


def test_removal_is_soft_and_hides_the_holiday_by_default(client, hr_headers):
    created = _create(client, hr_headers)
    assert client.delete(f"{API}/holidays/{created['id']}", headers=hr_headers).status_code == 200

    visible = client.get(f"{API}/holidays", params={"year": 2026}, headers=hr_headers).json()
    assert visible == []

    # The row survives, so past calendars stay intact.
    including = client.get(
        f"{API}/holidays",
        params={"year": 2026, "include_inactive": True},
        headers=hr_headers,
    ).json()
    assert [h["name"] for h in including] == ["Diwali"]
    assert including[0]["is_active"] is False


def test_an_employee_cannot_see_removed_holidays(client, hr_headers, employee_headers):
    """include_inactive is an HR affordance; for an employee it is quietly ignored."""
    created = _create(client, hr_headers)
    client.delete(f"{API}/holidays/{created['id']}", headers=hr_headers)

    response = client.get(
        f"{API}/holidays",
        params={"year": 2026, "include_inactive": True},
        headers=employee_headers,
    )
    assert response.status_code == 200
    assert response.json() == []


def test_removing_twice_is_rejected(client, hr_headers):
    created = _create(client, hr_headers)
    client.delete(f"{API}/holidays/{created['id']}", headers=hr_headers)
    assert client.delete(
        f"{API}/holidays/{created['id']}", headers=hr_headers
    ).status_code == 409


def test_unknown_ids_are_404_not_500(client, hr_headers):
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.patch(
        f"{API}/holidays/{missing}", json={"name": "X"}, headers=hr_headers
    ).status_code == 404
    assert client.delete(f"{API}/holidays/{missing}", headers=hr_headers).status_code == 404


# --- Validation --------------------------------------------------------------


def test_a_blank_name_is_rejected(client, hr_headers):
    response = client.post(
        f"{API}/holidays",
        json={"name": "   ", "holiday_date": "2026-11-08", "type": "public"},
        headers=hr_headers,
    )
    assert response.status_code == 422


def test_names_are_stored_trimmed(client, hr_headers):
    created = _create(client, hr_headers, name="  Diwali  ")
    assert created["name"] == "Diwali"


# --- Summary -----------------------------------------------------------------


def test_the_summary_counts_by_type_and_upcoming(client, hr_headers):
    reference = today()
    year = reference.year
    _create(client, hr_headers, name="Past Public", holiday_date=(reference - timedelta(days=5)).isoformat())
    _create(client, hr_headers, name="Next Public", holiday_date=(reference + timedelta(days=5)).isoformat())
    _create(client, hr_headers, name="Optional", holiday_date=(reference + timedelta(days=6)).isoformat(), type="restricted")
    _create(client, hr_headers, name="Founders", holiday_date=(reference + timedelta(days=7)).isoformat(), type="company")

    summary = client.get(f"{API}/holidays/summary", params={"year": year}, headers=hr_headers).json()
    assert summary["year"] == year
    assert summary["total"] == 4
    assert summary["upcoming"] == 3  # the past one is excluded
    assert (summary["public"], summary["restricted"], summary["company"]) == (2, 1, 1)


def test_removed_holidays_are_excluded_from_the_summary(client, hr_headers):
    created = _create(client, hr_headers, holiday_date=f"{today().year}-11-08")
    client.delete(f"{API}/holidays/{created['id']}", headers=hr_headers)
    summary = client.get(f"{API}/holidays/summary", headers=hr_headers).json()
    assert summary["total"] == 0


# --- Audit -------------------------------------------------------------------


def test_calendar_changes_are_audited(client, hr_headers, db):
    from app.models.audit import AuditLog
    from sqlalchemy import select

    created = _create(client, hr_headers)
    client.patch(f"{API}/holidays/{created['id']}", json={"name": "Deepavali"}, headers=hr_headers)
    client.delete(f"{API}/holidays/{created['id']}", headers=hr_headers)

    actions = db.scalars(
        select(AuditLog.action).where(AuditLog.entity_type == "holiday")
    ).all()
    assert set(actions) == {"holiday_created", "holiday_updated", "holiday_deleted"}
