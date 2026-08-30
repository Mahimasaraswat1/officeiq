"""The request engine: validation, routing, the self-approval guard, and notifications."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.employee import Employee
from app.models.enums import NotificationType, UserRole
from app.models.notification import Notification
from app.models.user import User
from tests.conftest import API, HR, _make_user, auth_headers

EMPLOYEE = {"email": "requester@example.com", "password": "Requester@123"}
LEAVE = {
    "leave_kind": "casual",
    "start_date": "2026-09-14",
    "end_date": "2026-09-16",
    "reason": "Family wedding",
}


def _link_employee(db: Session, user: User, *, code: str = "EMP9001") -> Employee:
    employee = Employee(
        employee_code=code,
        user_id=user.id,
        first_name="Asha",
        last_name="Rao",
        work_email=user.email,
    )
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


@pytest.fixture
def employee_ctx(client: TestClient, db: Session):
    user = _make_user(
        db, email=EMPLOYEE["email"], password=EMPLOYEE["password"], role=UserRole.EMPLOYEE
    )
    employee = _link_employee(db, user)
    headers = auth_headers(client, EMPLOYEE["email"], EMPLOYEE["password"])
    return {"user": user, "employee": employee, "headers": headers}


def _submit(client: TestClient, headers: dict, **overrides) -> dict:
    body = {"type": "leave", "payload": LEAVE | overrides}
    response = client.post(f"{API}/my-requests", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# --- Submission --------------------------------------------------------------


def test_an_employee_can_submit_leave_and_sees_it_pending(client, employee_ctx):
    created = _submit(client, employee_ctx["headers"])
    assert created["status"] == "pending"
    assert created["type"] == "leave"
    assert created["request_code"].startswith("REQ-")
    assert created["summary"] == "Casual leave · 3 days · 14 Sep – 16 Sep 2026"
    assert created["can_cancel"] is True
    assert created["can_decide"] is False  # own request


def test_request_codes_are_sequential_and_unique(client, employee_ctx):
    codes = [_submit(client, employee_ctx["headers"])["request_code"] for _ in range(3)]
    assert len(set(codes)) == 3
    assert [c.split("-")[-1] for c in codes] == ["0001", "0002", "0003"]


def test_a_backwards_date_range_is_rejected(client, employee_ctx):
    response = client.post(
        f"{API}/my-requests",
        json={"type": "leave", "payload": LEAVE | {"start_date": "2026-09-16", "end_date": "2026-09-14"}},
        headers=employee_ctx["headers"],
    )
    assert response.status_code == 422
    assert "end_date" in response.json()["error"]["message"]


def test_an_unknown_leave_kind_is_rejected(client, employee_ctx):
    response = client.post(
        f"{API}/my-requests",
        json={"type": "leave", "payload": LEAVE | {"leave_kind": "sabbatical"}},
        headers=employee_ctx["headers"],
    )
    assert response.status_code == 422


def test_a_half_day_must_be_a_single_date(client, employee_ctx):
    response = client.post(
        f"{API}/my-requests",
        json={"type": "leave", "payload": LEAVE | {"half_day": True}},
        headers=employee_ctx["headers"],
    )
    assert response.status_code == 422


def test_a_half_day_counts_as_half(client, employee_ctx):
    created = _submit(
        client, employee_ctx["headers"], start_date="2026-09-14", end_date="2026-09-14", half_day=True
    )
    assert "half day" in created["summary"]


def test_a_user_with_no_employee_record_cannot_submit(client, db):
    _make_user(db, email="orphan@example.com", password="Orphan@1234", role=UserRole.EMPLOYEE)
    headers = auth_headers(client, "orphan@example.com", "Orphan@1234")
    response = client.post(
        f"{API}/my-requests", json={"type": "leave", "payload": LEAVE}, headers=headers
    )
    assert response.status_code == 404


# --- Visibility --------------------------------------------------------------


def test_an_employee_sees_only_their_own_requests(client, db, employee_ctx, hr_headers):
    mine = _submit(client, employee_ctx["headers"])

    other_user = _make_user(db, email="other@example.com", password="Other@12345", role=UserRole.EMPLOYEE)
    _link_employee(db, other_user, code="EMP9002")
    other_headers = auth_headers(client, "other@example.com", "Other@12345")
    theirs = _submit(client, other_headers)

    visible = client.get(f"{API}/my-requests", headers=employee_ctx["headers"]).json()
    assert [r["request_code"] for r in visible] == [mine["request_code"]]

    # Someone else's id is a 404, not a 403 — a 403 would confirm it exists.
    assert client.get(
        f"{API}/requests/{theirs['id']}", headers=employee_ctx["headers"]
    ).status_code == 404


def test_an_employee_cannot_read_the_approval_queue(client, employee_ctx):
    assert client.get(f"{API}/requests", headers=employee_ctx["headers"]).status_code == 403


def test_hr_sees_every_request_in_the_queue(client, db, employee_ctx, hr_headers):
    _submit(client, employee_ctx["headers"])
    rows = client.get(f"{API}/requests", headers=hr_headers).json()
    assert len(rows) == 1
    assert rows[0]["employee_name"] == "Asha Rao"
    assert rows[0]["can_decide"] is True


def test_the_queue_can_be_filtered_by_status(client, employee_ctx, hr_headers):
    first = _submit(client, employee_ctx["headers"])
    _submit(client, employee_ctx["headers"])
    client.post(f"{API}/requests/{first['id']}/approve", json={}, headers=hr_headers)

    pending = client.get(f"{API}/requests", params={"status": "pending"}, headers=hr_headers).json()
    approved = client.get(f"{API}/requests", params={"status": "approved"}, headers=hr_headers).json()
    assert len(pending) == 1 and len(approved) == 1


# --- Decisions ---------------------------------------------------------------


def test_hr_can_approve_and_the_decision_is_recorded(client, employee_ctx, hr_headers):
    created = _submit(client, employee_ctx["headers"])
    decided = client.post(
        f"{API}/requests/{created['id']}/approve",
        json={"note": "Enjoy the wedding"},
        headers=hr_headers,
    ).json()

    assert decided["status"] == "approved"
    assert decided["decision_note"] == "Enjoy the wedding"
    assert decided["decided_at"] is not None
    assert decided["decided_by_name"]
    assert decided["can_decide"] is False  # no longer open


def test_rejecting_requires_a_reason(client, employee_ctx, hr_headers):
    created = _submit(client, employee_ctx["headers"])
    assert client.post(
        f"{API}/requests/{created['id']}/reject", json={}, headers=hr_headers
    ).status_code == 422
    assert client.post(
        f"{API}/requests/{created['id']}/reject", json={"note": "   "}, headers=hr_headers
    ).status_code == 422


def test_rejection_carries_the_reason_back(client, employee_ctx, hr_headers):
    created = _submit(client, employee_ctx["headers"])
    decided = client.post(
        f"{API}/requests/{created['id']}/reject",
        json={"note": "Team is short-staffed that week"},
        headers=hr_headers,
    ).json()
    assert decided["status"] == "rejected"
    assert decided["decision_note"] == "Team is short-staffed that week"


def test_a_decided_request_cannot_be_decided_again(client, employee_ctx, hr_headers):
    created = _submit(client, employee_ctx["headers"])
    client.post(f"{API}/requests/{created['id']}/approve", json={}, headers=hr_headers)

    again = client.post(f"{API}/requests/{created['id']}/approve", json={}, headers=hr_headers)
    assert again.status_code == 409
    assert "already approved" in again.json()["error"]["message"]


def test_an_employee_cannot_approve_anything(client, employee_ctx, hr_headers):
    created = _submit(client, employee_ctx["headers"])
    assert client.post(
        f"{API}/requests/{created['id']}/approve", json={}, headers=employee_ctx["headers"]
    ).status_code == 403


# --- The self-approval guard -------------------------------------------------


@pytest.fixture
def hr_own_request(client: TestClient, db: Session, hr_headers):
    """An HR user who has submitted their own leave request."""
    hr_user = db.scalar(select(User).where(User.email == HR["email"]))
    _link_employee(db, hr_user, code="EMP9500")
    created = _submit(client, hr_headers)
    return created


def test_hr_cannot_approve_their_own_request(client, hr_own_request, hr_headers):
    """Otherwise an HR user lands in the queue they themselves work."""
    response = client.post(
        f"{API}/requests/{hr_own_request['id']}/approve", json={}, headers=hr_headers
    )
    assert response.status_code == 403
    assert "cannot decide your own request" in response.json()["error"]["message"].lower()


def test_hr_cannot_reject_their_own_request_either(client, hr_own_request, hr_headers):
    response = client.post(
        f"{API}/requests/{hr_own_request['id']}/reject",
        json={"note": "changed my mind"},
        headers=hr_headers,
    )
    assert response.status_code == 403


def test_hr_sees_their_own_request_flagged_as_undecidable(client, hr_own_request, hr_headers):
    """The UI reads can_decide rather than re-deriving the rule and drifting."""
    rows = client.get(f"{API}/requests", headers=hr_headers).json()
    mine = next(r for r in rows if r["id"] == hr_own_request["id"])
    assert mine["can_decide"] is False
    assert mine["can_cancel"] is True


def test_an_admin_can_decide_an_hr_users_request(client, hr_own_request, admin_headers):
    """The escalation path: somebody must still be able to approve it."""
    decided = client.post(
        f"{API}/requests/{hr_own_request['id']}/approve", json={}, headers=admin_headers
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "approved"


# --- Cancellation ------------------------------------------------------------


def test_an_employee_can_withdraw_a_pending_request(client, employee_ctx):
    created = _submit(client, employee_ctx["headers"])
    cancelled = client.post(
        f"{API}/my-requests/{created['id']}/cancel", headers=employee_ctx["headers"]
    ).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["can_cancel"] is False


def test_a_decided_request_cannot_be_withdrawn(client, employee_ctx, hr_headers):
    created = _submit(client, employee_ctx["headers"])
    client.post(f"{API}/requests/{created['id']}/approve", json={}, headers=hr_headers)
    response = client.post(
        f"{API}/my-requests/{created['id']}/cancel", headers=employee_ctx["headers"]
    )
    assert response.status_code == 409


def test_one_employee_cannot_withdraw_anothers_request(client, db, employee_ctx):
    other_user = _make_user(db, email="other2@example.com", password="Other@12345", role=UserRole.EMPLOYEE)
    _link_employee(db, other_user, code="EMP9003")
    other_headers = auth_headers(client, "other2@example.com", "Other@12345")
    theirs = _submit(client, other_headers)

    response = client.post(
        f"{API}/my-requests/{theirs['id']}/cancel", headers=employee_ctx["headers"]
    )
    assert response.status_code == 404  # not even visible


# --- Notifications -----------------------------------------------------------


def test_submitting_notifies_hr(client, db, employee_ctx, hr_user):
    _submit(client, employee_ctx["headers"])
    rows = db.scalars(
        select(Notification).where(Notification.type == NotificationType.REQUEST_SUBMITTED)
    ).all()
    assert [n.user_id for n in rows] == [hr_user.id]
    assert "Asha Rao" in rows[0].title
    assert rows[0].body == "Casual leave · 3 days · 14 Sep – 16 Sep 2026"


def test_a_decision_notifies_the_employee(client, db, employee_ctx, hr_headers):
    created = _submit(client, employee_ctx["headers"])
    client.post(
        f"{API}/requests/{created['id']}/reject",
        json={"note": "Short-staffed"},
        headers=hr_headers,
    )
    rows = db.scalars(
        select(Notification).where(Notification.type == NotificationType.REQUEST_REJECTED)
    ).all()
    assert [n.user_id for n in rows] == [employee_ctx["user"].id]
    assert rows[0].body == "Short-staffed"


def test_hr_submitting_their_own_request_is_not_notified_about_it(
    client, db, hr_own_request, hr_user
):
    """Telling HR about their own click is noise, not news."""
    rows = db.scalars(
        select(Notification).where(
            Notification.type == NotificationType.REQUEST_SUBMITTED,
            Notification.user_id == hr_user.id,
        )
    ).all()
    assert rows == []


# --- Counts & audit ----------------------------------------------------------


def test_counts_report_each_status(client, employee_ctx, hr_headers):
    a = _submit(client, employee_ctx["headers"])
    b = _submit(client, employee_ctx["headers"])
    _submit(client, employee_ctx["headers"])
    client.post(f"{API}/requests/{a['id']}/approve", json={}, headers=hr_headers)
    client.post(f"{API}/requests/{b['id']}/reject", json={"note": "no"}, headers=hr_headers)

    counts = client.get(f"{API}/requests/counts", headers=hr_headers).json()
    assert counts == {"pending": 1, "approved": 1, "rejected": 1, "cancelled": 0}


def test_the_lifecycle_is_audited(client, db, employee_ctx, hr_headers):
    from app.models.audit import AuditLog

    created = _submit(client, employee_ctx["headers"])
    client.post(f"{API}/requests/{created['id']}/approve", json={}, headers=hr_headers)

    actions = db.scalars(
        select(AuditLog.action).where(AuditLog.entity_type == "request")
    ).all()
    assert set(actions) == {"request_submitted", "request_approved"}
