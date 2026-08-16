"""In-app notifications: fan-out, privacy, reminders (PRD A.7.7)."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.employee import Employee
from app.models.enums import NotificationType, TaskStatus
from app.models.notification import Notification
from app.models.task import EmployeeTask
from app.services.notifications import run_task_reminders
from tests.conftest import API
from tests.factories import (
    AADHAAR_TEXT,
    make_png,
    make_text_pdf,
    upload_file,
)

EMPLOYEE = {
    "first_name": "Ananya",
    "last_name": "Sharma",
    "work_email": "ananya.notify@example.com",
    "department": "Engineering",
    "designation": "Software Engineer",
}


@pytest.fixture
def employee_id(client, hr_headers) -> str:
    return client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers).json()["id"]


def _accept_invite(client, password="Ananya@12345") -> None:
    files = sorted(Path(settings.EMAIL_OUTBOX_DIR).glob("*.txt"))
    token = re.search(r"accept-invite\?token=([A-Za-z0-9_\-]+)", files[-1].read_text()).group(1)
    response = client.post(
        f"{API}/onboarding/accept", json={"token": token, "password": password}
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def employee_headers(client, hr_headers, employee_id) -> dict[str, str]:
    _accept_invite(client)
    tokens = client.post(
        f"{API}/auth/login",
        json={"email": EMPLOYEE["work_email"], "password": "Ananya@12345"},
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def notifications_of(client, headers, **params) -> list[dict]:
    response = client.get(f"{API}/notifications", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def types_of(items: list[dict]) -> set[str]:
    return {item["type"] for item in items}


# --- Fan-out ---------------------------------------------------------------


def test_accepting_an_invitation_notifies_hr(client, hr_headers, employee_id):
    _accept_invite(client)

    items = notifications_of(client, hr_headers)
    accepted = [i for i in items if i["type"] == NotificationType.INVITATION_ACCEPTED.value]
    assert len(accepted) == 1
    assert "Ananya Sharma" in accepted[0]["title"]
    assert accepted[0]["link"] == f"/employees/{employee_id}"
    assert accepted[0]["is_read"] is False


def test_document_upload_notifies_hr_but_not_the_uploading_employee(
    client, hr_headers, employee_headers, employee_id
):
    upload_file(
        client,
        employee_headers,
        employee_id,
        data=make_png(),
        filename="photo.png",
        document_type="photo",
    )

    assert NotificationType.DOCUMENT_UPLOADED.value in types_of(
        notifications_of(client, hr_headers)
    )
    # The employee already knows they uploaded it.
    assert NotificationType.DOCUMENT_UPLOADED.value not in types_of(
        notifications_of(client, employee_headers)
    )


def test_hr_uploading_does_not_notify_the_uploader(client, hr_headers, employee_id):
    """The actor is excluded from their own operational event."""
    upload_file(
        client,
        hr_headers,
        employee_id,
        data=make_png(),
        filename="photo.png",
        document_type="photo",
    )

    uploads = [
        i
        for i in notifications_of(client, hr_headers)
        if i["type"] == NotificationType.DOCUMENT_UPLOADED.value
    ]
    assert uploads == []


def test_document_rejection_tells_the_employee_the_reason(
    client, hr_headers, employee_headers, employee_id
):
    document_id = upload_file(
        client,
        employee_headers,
        employee_id,
        data=make_png(),
        filename="photo.png",
        document_type="photo",
    ).json()["id"]

    reason = "The photo is too blurry to verify — please upload a clearer one."
    response = client.post(
        f"{API}/documents/{document_id}/reject",
        json={"reason": reason},
        headers=hr_headers,
    )
    assert response.status_code == 200, response.text

    rejected = [
        i
        for i in notifications_of(client, employee_headers)
        if i["type"] == NotificationType.DOCUMENT_REJECTED.value
    ]
    assert len(rejected) == 1
    # The reason is the actionable part; a notification without it is useless.
    assert rejected[0]["body"] == reason
    assert rejected[0]["link"] == "/my-onboarding"


def test_document_approval_notifies_the_employee(
    client, hr_headers, employee_headers, employee_id
):
    document_id = upload_file(
        client,
        employee_headers,
        employee_id,
        data=make_png(),
        filename="photo.png",
        document_type="photo",
    ).json()["id"]
    client.post(f"{API}/documents/{document_id}/approve", json={}, headers=hr_headers)

    assert NotificationType.DOCUMENT_APPROVED.value in types_of(
        notifications_of(client, employee_headers)
    )


def test_task_assignment_notifies_the_employee_once(
    client, hr_headers, employee_headers, employee_id, db
):
    template_id = client.post(
        f"{API}/task-templates",
        json={"code": "handbook", "title": "Read the handbook", "category": "task"},
        headers=hr_headers,
    ).json()["id"]
    client.post(
        f"{API}/assignment-rules",
        json={"name": "Everyone", "items": [{"template_id": template_id}]},
        headers=hr_headers,
    )

    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)
    # Re-running is idempotent, so it must not produce a second announcement.
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)

    assigned = [
        i
        for i in notifications_of(client, employee_headers)
        if i["type"] == NotificationType.TASKS_ASSIGNED.value
    ]
    assert len(assigned) == 1
    assert assigned[0]["detail"]["count"] == 1


def test_unregistered_employee_produces_no_orphan_notification(
    client, hr_headers, employee_id, db
):
    """An invited-but-not-registered person has no account to notify."""
    document_id = upload_file(
        client,
        hr_headers,
        employee_id,
        data=make_png(),
        filename="photo.png",
        document_type="photo",
    ).json()["id"]
    client.post(
        f"{API}/documents/{document_id}/reject",
        json={"reason": "Please resubmit a clearer photograph."},
        headers=hr_headers,
    )

    rejected = db.scalars(
        select(Notification).where(
            Notification.type == NotificationType.DOCUMENT_REJECTED
        )
    ).all()
    assert rejected == []


def test_failed_id_verification_notifies_hr(client, hr_headers, employee_id):
    """A checksum failure is a judgement call, so it lands in HR's inbox."""
    bad_aadhaar = AADHAAR_TEXT.replace("2341 2341 2346", "2341 2341 2345")
    upload_file(
        client,
        hr_headers,
        employee_id,
        data=make_text_pdf(bad_aadhaar),
        filename="aadhaar.pdf",
        document_type="aadhaar",
        content_type="application/pdf",
    )

    failures = [
        i
        for i in notifications_of(client, hr_headers)
        if i["type"] == NotificationType.VERIFICATION_FAILED.value
    ]
    assert failures, "a failed ID check should reach HR"
    assert failures[0]["detail"]["check_type"] == "aadhaar"


def test_chat_escalation_shares_the_question_not_the_conversation(
    client, hr_headers, employee_headers
):
    question = "What is the reimbursement limit for a relocation allowance?"
    response = client.post(
        f"{API}/chat/ask", json={"question": question}, headers=employee_headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["escalated"] is True, "no knowledge base means escalation"

    escalations = [
        i
        for i in notifications_of(client, hr_headers)
        if i["type"] == NotificationType.CHAT_ESCALATED.value
    ]
    assert len(escalations) == 1
    assert escalations[0]["body"] == question
    # A conversation id would be a doorway into a private transcript.
    assert escalations[0]["entity_type"] == "user"


# --- Inbox behaviour -------------------------------------------------------


def test_inbox_is_private_to_its_owner(client, hr_headers, employee_headers, employee_id):
    _ = notifications_of(client, hr_headers)
    hr_ids = {i["id"] for i in notifications_of(client, hr_headers)}
    employee_ids = {i["id"] for i in notifications_of(client, employee_headers)}
    assert hr_ids.isdisjoint(employee_ids)


def test_admin_cannot_read_another_users_notification(
    client, admin_headers, hr_headers, employee_headers, employee_id
):
    """Even Admin has no route into someone else's inbox."""
    _accept_invite  # noqa: B018 - invitation already accepted by the fixture
    hr_items = notifications_of(client, hr_headers)
    assert hr_items, "fixture should have produced at least one HR notification"

    response = client.post(
        f"{API}/notifications/{hr_items[0]['id']}/read", headers=admin_headers
    )
    # Indistinguishable from a nonexistent id, so it leaks nothing.
    assert response.status_code == 404


def test_unread_count_and_mark_read_flow(client, hr_headers, employee_id):
    _accept_invite(client)

    before = client.get(f"{API}/notifications/unread-count", headers=hr_headers).json()
    assert before["unread"] >= 1

    items = notifications_of(client, hr_headers, unread_only=True)
    read = client.post(f"{API}/notifications/{items[0]['id']}/read", headers=hr_headers)
    assert read.status_code == 200
    assert read.json()["is_read"] is True
    assert read.json()["read_at"] is not None

    after = client.get(f"{API}/notifications/unread-count", headers=hr_headers).json()
    assert after["unread"] == before["unread"] - 1

    # Marking an already-read notification again is a no-op, not an error.
    assert client.post(
        f"{API}/notifications/{items[0]['id']}/read", headers=hr_headers
    ).status_code == 200


def test_read_all_clears_the_badge(client, hr_headers, employee_id):
    _accept_invite(client)
    upload_file(
        client,
        hr_headers,
        employee_id,
        data=make_png(),
        filename="photo.png",
        document_type="photo",
    )

    response = client.post(f"{API}/notifications/read-all", headers=hr_headers)
    assert response.status_code == 200
    assert response.json()["marked_read"] >= 1
    assert client.get(
        f"{API}/notifications/unread-count", headers=hr_headers
    ).json()["unread"] == 0


def test_dismiss_removes_only_that_notification(client, hr_headers, employee_id):
    _accept_invite(client)
    items = notifications_of(client, hr_headers)
    target = items[0]["id"]

    assert client.delete(f"{API}/notifications/{target}", headers=hr_headers).status_code == 200
    remaining = {i["id"] for i in notifications_of(client, hr_headers)}
    assert target not in remaining


def test_filtering_by_type(client, hr_headers, employee_id):
    _accept_invite(client)
    upload_file(
        client,
        hr_headers,
        employee_id,
        data=make_png(),
        filename="photo.png",
        document_type="photo",
    )

    filtered = notifications_of(
        client, hr_headers, type=NotificationType.INVITATION_ACCEPTED.value
    )
    assert filtered
    assert types_of(filtered) == {NotificationType.INVITATION_ACCEPTED.value}


def test_notifications_require_authentication(client):
    assert client.get(f"{API}/notifications").status_code == 401


# --- Reminders -------------------------------------------------------------


def _add_task(db, employee_id: str, *, title: str, due: date) -> EmployeeTask:
    task = EmployeeTask(
        employee_id=employee_id,
        title=title,
        category="task",
        due_date=due,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.commit()
    return task


def test_reminders_flag_overdue_and_due_soon(client, hr_headers, employee_headers, db, employee_id):
    employee = db.scalar(select(Employee).where(Employee.work_email == EMPLOYEE["work_email"]))
    today = date.today()
    _add_task(db, employee.id, title="Sign the policy", due=today - timedelta(days=2))
    _add_task(db, employee.id, title="Book induction", due=today + timedelta(days=1))
    # Comfortably outside the due-soon horizon.
    _add_task(db, employee.id, title="Later thing", due=today + timedelta(days=60))

    response = client.post(f"{API}/notifications/run-reminders", headers=hr_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {"due_soon": 1, "overdue": 1}

    items = notifications_of(client, employee_headers)
    assert NotificationType.TASK_OVERDUE.value in types_of(items)
    assert NotificationType.TASK_DUE_SOON.value in types_of(items)
    assert not any("Later thing" in i["title"] for i in items)


def test_reminders_are_idempotent_while_unread(client, hr_headers, db, employee_id, employee_headers):
    employee = db.scalar(select(Employee).where(Employee.work_email == EMPLOYEE["work_email"]))
    _add_task(db, employee.id, title="Sign the policy", due=date.today() - timedelta(days=2))

    first = client.post(f"{API}/notifications/run-reminders", headers=hr_headers).json()
    second = client.post(f"{API}/notifications/run-reminders", headers=hr_headers).json()

    assert first["overdue"] == 1
    # A scheduler runs this repeatedly; a second row would bury the inbox.
    assert second["overdue"] == 0


def test_reminders_skip_closed_tasks(db, employee_id, client, hr_headers):
    employee = db.scalar(select(Employee).where(Employee.work_email == EMPLOYEE["work_email"]))
    task = _add_task(db, employee.id, title="Done already", due=date.today() - timedelta(days=5))
    task.status = TaskStatus.COMPLETED
    db.commit()

    assert run_task_reminders(db) == {"due_soon": 0, "overdue": 0}


def test_running_reminders_requires_hr(client, employee_headers):
    assert client.post(
        f"{API}/notifications/run-reminders", headers=employee_headers
    ).status_code == 403
