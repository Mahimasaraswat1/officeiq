"""HR dashboard analytics: summary, funnel, trends, attention queue (PRD A.9/A.10)."""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from pathlib import Path

from app.core.config import settings
from app.core.security import utcnow, today_utc
from app.models.employee import Employee
from app.models.enums import OnboardingStatus, TaskStatus
from app.models.task import EmployeeTask
from tests.conftest import API
from tests.factories import AADHAAR_TEXT, make_png, make_text_pdf, upload_file


def create_employee(client, hr_headers, **overrides) -> uuid.UUID:
    """Returns a real UUID — SQLite's Uuid column rejects the string form."""
    payload = {
        "first_name": "Ananya",
        "last_name": "Sharma",
        "work_email": "ananya.dash@example.com",
        "department": "Engineering",
        "designation": "Software Engineer",
        **overrides,
    }
    response = client.post(f"{API}/employees", json=payload, headers=hr_headers)
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


def accept_latest_invite(client, email, password="Ananya@12345") -> dict[str, str]:
    files = sorted(Path(settings.EMAIL_OUTBOX_DIR).glob("*.txt"))
    token = re.search(r"accept-invite\?token=([A-Za-z0-9_\-]+)", files[-1].read_text()).group(1)
    client.post(f"{API}/onboarding/accept", json={"token": token, "password": password})
    tokens = client.post(
        f"{API}/auth/login", json={"email": email, "password": password}
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# --- Access control --------------------------------------------------------


def test_dashboard_is_hr_only(client, hr_headers):
    create_employee(client, hr_headers)
    employee_headers = accept_latest_invite(client, "ananya.dash@example.com")

    for path in ("/dashboard/summary", "/dashboard/funnel", "/dashboard/attention",
                 "/dashboard/trends", "/dashboard/departments"):
        assert client.get(f"{API}{path}", headers=employee_headers).status_code == 403
        assert client.get(f"{API}{path}").status_code == 401


def test_admin_can_read_the_dashboard(client, admin_headers):
    assert client.get(f"{API}/dashboard/summary", headers=admin_headers).status_code == 200


# --- Summary ---------------------------------------------------------------


def test_summary_on_an_empty_workspace_is_all_zeros(client, hr_headers):
    """A fresh install must render, not divide by zero."""
    body = client.get(f"{API}/dashboard/summary", headers=hr_headers).json()

    assert body["employees_total"] == 0
    assert body["task_completion_rate"] == 0.0
    assert body["chat_resolution_rate"] == 0.0
    assert body["average_days_to_complete"] is None


def test_summary_counts_people_by_state(client, hr_headers, db):
    create_employee(client, hr_headers)
    second = create_employee(
        client, hr_headers, work_email="rohit.dash@example.com", first_name="Rohit"
    )

    employee = db.get(Employee, second)
    employee.onboarding_status = OnboardingStatus.COMPLETE
    employee.onboarding_completed_at = utcnow()
    db.commit()

    body = client.get(f"{API}/dashboard/summary", headers=hr_headers).json()
    assert body["employees_total"] == 2
    assert body["onboarding_complete"] == 1
    assert body["onboarding_in_progress"] == 1
    assert body["completed_in_window"] == 1
    # created_at and completed_at are moments apart, so this rounds to ~0 days.
    assert body["average_days_to_complete"] is not None


def test_average_days_to_complete_measures_elapsed_time(client, hr_headers, db):
    employee_id = create_employee(client, hr_headers)
    employee = db.get(Employee, employee_id)
    employee.created_at = utcnow() - timedelta(days=10)
    employee.onboarding_status = OnboardingStatus.COMPLETE
    employee.onboarding_completed_at = utcnow()
    db.commit()

    body = client.get(f"{API}/dashboard/summary", headers=hr_headers).json()
    assert 9.5 <= body["average_days_to_complete"] <= 10.5


def test_summary_reports_document_and_task_state(client, hr_headers, db):
    employee_id = create_employee(client, hr_headers)
    upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="photo.png", document_type="photo",
    )

    db.add_all([
        EmployeeTask(employee_id=employee_id, title="Open", category="task",
                     status=TaskStatus.PENDING),
        EmployeeTask(employee_id=employee_id, title="Done", category="task",
                     status=TaskStatus.COMPLETED),
        EmployeeTask(employee_id=employee_id, title="Late", category="task",
                     status=TaskStatus.PENDING, due_date=today_utc() - timedelta(days=3)),
    ])
    db.commit()

    body = client.get(f"{API}/dashboard/summary", headers=hr_headers).json()
    assert body["documents_pending_review"] == 1  # extraction ran inline in tests
    assert body["tasks_open"] == 2
    assert body["tasks_overdue"] == 1
    assert body["task_completion_rate"] == round(1 / 3, 4)


def test_summary_task_rate_counts_a_waiver_as_closed(client, hr_headers, db):
    employee_id = create_employee(client, hr_headers)
    db.add_all([
        EmployeeTask(employee_id=employee_id, title="Waived", category="task",
                     status=TaskStatus.WAIVED, waiver_reason="Not applicable to this role"),
        EmployeeTask(employee_id=employee_id, title="Open", category="task",
                     status=TaskStatus.PENDING),
    ])
    db.commit()

    body = client.get(f"{API}/dashboard/summary", headers=hr_headers).json()
    assert body["task_completion_rate"] == 0.5


def test_summary_chat_rate_matches_chat_analytics(client, hr_headers):
    """Two endpoints reporting the same KPI must not disagree."""
    create_employee(client, hr_headers)
    employee_headers = accept_latest_invite(client, "ananya.dash@example.com")
    client.post(f"{API}/chat/ask", json={"question": "What is the leave policy here?"},
                headers=employee_headers)

    dashboard = client.get(f"{API}/dashboard/summary", headers=hr_headers).json()
    analytics = client.get(f"{API}/chat/analytics", headers=hr_headers).json()

    assert dashboard["questions_total"] == analytics["questions_total"]
    assert dashboard["chat_resolution_rate"] == analytics["resolution_rate"]


def test_joining_soon_counts_only_the_next_30_days(client, hr_headers):
    today = today_utc()
    create_employee(client, hr_headers, date_of_joining=str(today + timedelta(days=5)))
    create_employee(client, hr_headers, work_email="far@example.com",
                    date_of_joining=str(today + timedelta(days=90)))
    create_employee(client, hr_headers, work_email="past@example.com",
                    date_of_joining=str(today - timedelta(days=5)))

    body = client.get(f"{API}/dashboard/summary", headers=hr_headers).json()
    assert body["joining_next_30_days"] == 1


# --- Funnel and departments ------------------------------------------------


def test_funnel_lists_every_stage_even_when_empty(client, hr_headers):
    create_employee(client, hr_headers)

    body = client.get(f"{API}/dashboard/funnel", headers=hr_headers).json()
    stages = {s["status"]: s["count"] for s in body["stages"]}

    assert stages[OnboardingStatus.INVITED.value] == 1
    # Empty stages still render, so the funnel keeps its shape.
    assert stages[OnboardingStatus.COMPLETE.value] == 0
    assert len(body["stages"]) == 7
    # REJECTED is an exit, not a rung.
    assert OnboardingStatus.REJECTED.value not in stages


def test_funnel_total_includes_rejected_even_though_no_stage_shows_it(
    client, hr_headers, db
):
    create_employee(client, hr_headers)
    second = create_employee(client, hr_headers, work_email="rohit.dash@example.com")
    db.get(Employee, second).onboarding_status = OnboardingStatus.REJECTED
    db.commit()

    body = client.get(f"{API}/dashboard/funnel", headers=hr_headers).json()
    assert body["total"] == 2
    assert sum(s["count"] for s in body["stages"]) == 1


def test_departments_bucket_unassigned_people(client, hr_headers):
    create_employee(client, hr_headers)
    create_employee(client, hr_headers, work_email="nodept@example.com", department=None)

    rows = client.get(f"{API}/dashboard/departments", headers=hr_headers).json()
    by_name = {row["department"]: row for row in rows}

    assert by_name["Engineering"]["total"] == 1
    # Someone with no department must still be counted somewhere.
    assert by_name["Unassigned"]["total"] == 1
    assert by_name["Engineering"]["in_progress"] == 1


# --- Trends ----------------------------------------------------------------


def test_trends_return_one_point_per_day_including_quiet_ones(client, hr_headers):
    create_employee(client, hr_headers)

    body = client.get(f"{API}/dashboard/trends", headers=hr_headers, params={"days": 7}).json()

    assert body["days"] == 7
    assert len(body["points"]) == 7
    # Days with no activity are present with zeros, so a chart has no gaps.
    assert body["points"][0]["profiles_created"] == 0
    assert body["points"][-1]["date"] == today_utc().isoformat()
    assert body["points"][-1]["profiles_created"] == 1


def test_trends_count_uploads_and_questions(client, hr_headers):
    employee_id = create_employee(client, hr_headers)
    employee_headers = accept_latest_invite(client, "ananya.dash@example.com")
    upload_file(client, employee_headers, employee_id, data=make_png(),
                filename="photo.png", document_type="photo")
    client.post(f"{API}/chat/ask", json={"question": "How many casual leaves do I get?"},
                headers=employee_headers)

    today = client.get(
        f"{API}/dashboard/trends", headers=hr_headers, params={"days": 2}
    ).json()["points"][-1]

    assert today["documents_uploaded"] == 1
    assert today["questions_asked"] == 1
    assert today["registrations"] == 1


def test_trends_reject_an_absurd_window(client, hr_headers):
    assert client.get(
        f"{API}/dashboard/trends", headers=hr_headers, params={"days": 4000}
    ).status_code == 422


# --- Attention queue -------------------------------------------------------


def test_attention_lists_documents_waiting_on_review(client, hr_headers):
    employee_id = create_employee(client, hr_headers)
    upload_file(client, hr_headers, employee_id, data=make_png(),
                filename="photo.png", document_type="photo")

    group = client.get(f"{API}/dashboard/attention", headers=hr_headers).json()[
        "documents_pending_review"
    ]
    assert group["total"] == 1
    assert group["items"][0]["employee_name"] == "Ananya Sharma"
    assert group["items"][0]["original_filename"] == "photo.png"
    assert group["items"][0]["days_waiting"] == 0


def test_attention_drops_a_document_once_it_is_decided(client, hr_headers):
    employee_id = create_employee(client, hr_headers)
    document_id = upload_file(client, hr_headers, employee_id, data=make_png(),
                              filename="photo.png", document_type="photo").json()["id"]
    client.post(f"{API}/documents/{document_id}/approve", json={}, headers=hr_headers)

    body = client.get(f"{API}/dashboard/attention", headers=hr_headers).json()
    assert body["documents_pending_review"]["total"] == 0


def test_attention_surfaces_failed_verifications(client, hr_headers):
    employee_id = create_employee(client, hr_headers)
    bad = AADHAAR_TEXT.replace("2341 2341 2346", "2341 2341 2345")
    upload_file(client, hr_headers, employee_id, data=make_text_pdf(bad),
                filename="aadhaar.pdf", document_type="aadhaar",
                content_type="application/pdf")

    group = client.get(f"{API}/dashboard/attention", headers=hr_headers).json()[
        "failed_verifications"
    ]
    assert group["total"] >= 1
    assert group["items"][0]["check_type"] == "aadhaar"
    assert group["items"][0]["reason_code"]


def test_attention_orders_overdue_tasks_worst_first(client, hr_headers, db):
    employee_id = create_employee(client, hr_headers)
    today = today_utc()
    db.add_all([
        EmployeeTask(employee_id=employee_id, title="Slightly late", category="task",
                     status=TaskStatus.PENDING, due_date=today - timedelta(days=1)),
        EmployeeTask(employee_id=employee_id, title="Very late", category="task",
                     status=TaskStatus.PENDING, due_date=today - timedelta(days=30)),
        EmployeeTask(employee_id=employee_id, title="Not due yet", category="task",
                     status=TaskStatus.PENDING, due_date=today + timedelta(days=5)),
    ])
    db.commit()

    group = client.get(f"{API}/dashboard/attention", headers=hr_headers).json()["overdue_tasks"]
    assert group["total"] == 2
    assert group["items"][0]["title"] == "Very late"
    assert group["items"][0]["days_overdue"] == 30


def test_attention_flags_a_stalled_onboarding(client, hr_headers, db):
    employee_id = create_employee(client, hr_headers)
    employee = db.get(Employee, employee_id)
    employee.updated_at = utcnow() - timedelta(days=settings.ONBOARDING_STALLED_DAYS + 3)
    db.commit()

    group = client.get(f"{API}/dashboard/attention", headers=hr_headers).json()[
        "stalled_onboardings"
    ]
    assert group["total"] == 1
    assert group["items"][0]["days_since_update"] >= settings.ONBOARDING_STALLED_DAYS


def test_attention_ignores_a_stalled_but_finished_onboarding(client, hr_headers, db):
    """A completed record is not stalled; nobody needs to chase it."""
    employee_id = create_employee(client, hr_headers)
    employee = db.get(Employee, employee_id)
    employee.onboarding_status = OnboardingStatus.COMPLETE
    employee.updated_at = utcnow() - timedelta(days=90)
    db.commit()

    body = client.get(f"{API}/dashboard/attention", headers=hr_headers).json()
    assert body["stalled_onboardings"]["total"] == 0


def test_attention_reports_the_true_total_beyond_the_display_cap(client, hr_headers, db):
    """A capped list must not read as a short backlog."""
    employee_id = create_employee(client, hr_headers)
    db.add_all([
        EmployeeTask(employee_id=employee_id, title=f"Late {i}", category="task",
                     status=TaskStatus.PENDING, due_date=today_utc() - timedelta(days=i + 1))
        for i in range(6)
    ])
    db.commit()

    group = client.get(
        f"{API}/dashboard/attention", headers=hr_headers, params={"limit": 2}
    ).json()["overdue_tasks"]

    assert len(group["items"]) == 2
    assert group["total"] == 6
