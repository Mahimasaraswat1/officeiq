"""Task template / rule administration and the employee task API."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.enums import AuditAction
from tests.conftest import API
from tests.factories import AADHAAR_TEXT, PAN_TEXT, make_png, make_text_pdf, upload_file

EMPLOYEE = {
    "first_name": "Ananya",
    "last_name": "Sharma",
    "work_email": "ananya.tasks@example.com",
    "department": "Engineering",
    "designation": "Software Engineer",
}


@pytest.fixture
def employee_id(client, hr_headers) -> str:
    return client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers).json()["id"]


@pytest.fixture
def employee_login(client, hr_headers, employee_id):
    """Activate the invited employee and return their auth headers."""
    files = sorted(Path(settings.EMAIL_OUTBOX_DIR).glob("*.txt"))
    token = re.search(r"accept-invite\?token=([A-Za-z0-9_\-]+)", files[-1].read_text()).group(1)
    client.post(f"{API}/onboarding/accept", json={"token": token, "password": "Ananya@12345"})
    tokens = client.post(
        f"{API}/auth/login",
        json={"email": EMPLOYEE["work_email"], "password": "Ananya@12345"},
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def create_template(client, headers, code, **kwargs):
    payload = {"code": code, "title": kwargs.pop("title", code.title()), **kwargs}
    return client.post(f"{API}/task-templates", json=payload, headers=headers)


def create_rule(client, headers, name, template_ids, **kwargs):
    payload = {
        "name": name,
        "items": [{"template_id": tid} for tid in template_ids],
        **kwargs,
    }
    return client.post(f"{API}/assignment-rules", json=payload, headers=headers)


# --- Template administration -----------------------------------------------


def test_hr_can_create_a_template(client, hr_headers):
    response = create_template(client, hr_headers, "IT_LAPTOP", title="Collect laptop",
                               default_due_days=2)
    assert response.status_code == 201
    assert response.json()["code"] == "IT_LAPTOP"
    assert response.json()["default_due_days"] == 2


def test_template_code_is_normalised(client, hr_headers):
    response = create_template(client, hr_headers, "  it laptop  ")
    assert response.status_code == 201
    assert response.json()["code"] == "IT_LAPTOP"


def test_duplicate_template_code_is_a_conflict(client, hr_headers):
    create_template(client, hr_headers, "DUP")
    assert create_template(client, hr_headers, "DUP").status_code == 409


def test_checklist_template_requires_a_document_type(client, hr_headers):
    """Without one it could never complete itself, which defeats the point."""
    response = create_template(
        client, hr_headers, "DOC_X", category="document_checklist"
    )
    assert response.status_code == 422
    assert "required_document_type" in response.json()["error"]["message"]

    ok = create_template(
        client, hr_headers, "DOC_Y", category="document_checklist",
        required_document_type="aadhaar",
    )
    assert ok.status_code == 201


def test_employee_cannot_manage_templates(client, employee_login):
    assert client.get(f"{API}/task-templates", headers=employee_login).status_code == 403
    assert create_template(client, employee_login, "NOPE").status_code == 403


def test_template_can_be_updated_and_deactivated(client, hr_headers):
    template = create_template(client, hr_headers, "T1").json()

    response = client.patch(
        f"{API}/task-templates/{template['id']}",
        json={"title": "Renamed", "is_active": False},
        headers=hr_headers,
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Renamed"
    assert response.json()["is_active"] is False

    # Inactive templates are hidden by default.
    listed = client.get(f"{API}/task-templates", headers=hr_headers).json()
    assert all(t["code"] != "T1" for t in listed)
    with_inactive = client.get(
        f"{API}/task-templates?include_inactive=true", headers=hr_headers
    ).json()
    assert any(t["code"] == "T1" for t in with_inactive)


def test_assigned_template_cannot_be_deleted(client, hr_headers, admin_headers, employee_id):
    template = create_template(client, hr_headers, "T1").json()
    create_rule(client, hr_headers, "All", [template["id"]])
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)

    response = client.delete(f"{API}/task-templates/{template['id']}", headers=admin_headers)
    assert response.status_code == 409
    assert "Deactivate it instead" in response.json()["error"]["message"]


def test_unassigned_template_can_be_deleted_by_admin_only(
    client, hr_headers, admin_headers
):
    template = create_template(client, hr_headers, "T1").json()

    assert client.delete(
        f"{API}/task-templates/{template['id']}", headers=hr_headers
    ).status_code == 403
    assert client.delete(
        f"{API}/task-templates/{template['id']}", headers=admin_headers
    ).status_code == 200


# --- Rule administration ---------------------------------------------------


def test_hr_can_create_a_rule_without_a_deploy(client, hr_headers):
    """The whole point of DB-driven rules: HR edits policy at runtime."""
    template = create_template(client, hr_headers, "T1").json()

    response = create_rule(
        client, hr_headers, "Engineering", [template["id"]], department="Engineering"
    )
    assert response.status_code == 201
    body = response.json()
    assert body["department"] == "Engineering"
    assert len(body["items"]) == 1
    assert body["items"][0]["template"]["code"] == "T1"


def test_blank_condition_means_any(client, hr_headers):
    """An empty form field must mean 'any', not 'match the empty string'."""
    template = create_template(client, hr_headers, "T1").json()
    rule = create_rule(
        client, hr_headers, "All", [template["id"]], department="", designation="  "
    ).json()

    assert rule["department"] is None
    assert rule["designation"] is None


def test_rule_items_are_replaced_wholesale_on_update(client, hr_headers):
    first = create_template(client, hr_headers, "T1").json()
    second = create_template(client, hr_headers, "T2").json()
    rule = create_rule(client, hr_headers, "All", [first["id"]]).json()

    response = client.patch(
        f"{API}/assignment-rules/{rule['id']}",
        json={"items": [{"template_id": second["id"], "due_days_override": 3}]},
        headers=hr_headers,
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["template"]["code"] == "T2"
    assert items[0]["due_days_override"] == 3


def test_rule_referencing_an_unknown_template_is_rejected(client, hr_headers):
    response = create_rule(
        client, hr_headers, "Bad", ["00000000-0000-0000-0000-000000000000"]
    )
    assert response.status_code == 422


def test_deleting_a_rule_leaves_assigned_tasks_intact(client, hr_headers, employee_id):
    template = create_template(client, hr_headers, "T1").json()
    rule = create_rule(client, hr_headers, "All", [template["id"]]).json()
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)

    assert client.delete(f"{API}/assignment-rules/{rule['id']}", headers=hr_headers).status_code == 200

    tasks = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()
    assert len(tasks) == 1


def test_rule_preview_shows_what_would_be_assigned(client, hr_headers):
    base = create_template(client, hr_headers, "BASE").json()
    eng = create_template(client, hr_headers, "ENG").json()
    create_rule(client, hr_headers, "All", [base["id"]])
    create_rule(client, hr_headers, "Engineering", [eng["id"]], department="Engineering")

    response = client.post(
        f"{API}/assignment-rules/preview",
        json={"department": "Engineering"},
        headers=hr_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body["matched_rules"]) == {"All", "Engineering"}
    assert {t["code"] for t in body["templates"]} == {"BASE", "ENG"}


def test_rule_changes_are_audited(client, hr_headers, db):
    template = create_template(client, hr_headers, "T1").json()
    rule = create_rule(client, hr_headers, "All", [template["id"]]).json()
    client.patch(
        f"{API}/assignment-rules/{rule['id']}", json={"name": "Renamed"}, headers=hr_headers
    )

    actions = {row.action for row in db.scalars(select(AuditLog)).all()}
    assert AuditAction.TASK_TEMPLATE_CREATED.value in actions
    assert AuditAction.ASSIGNMENT_RULE_CREATED.value in actions
    assert AuditAction.ASSIGNMENT_RULE_UPDATED.value in actions


# --- Assignment through the API --------------------------------------------


def test_hr_can_run_assignment(client, hr_headers, employee_id):
    base = create_template(client, hr_headers, "BASE").json()
    eng = create_template(client, hr_headers, "ENG").json()
    create_rule(client, hr_headers, "All", [base["id"]])
    create_rule(client, hr_headers, "Engineering", [eng["id"]], department="Engineering")

    response = client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)
    assert response.status_code == 200
    assert response.json()["assigned_count"] == 2
    assert set(response.json()["matched_rules"]) == {"All", "Engineering"}


def test_rerunning_assignment_reports_no_new_tasks(client, hr_headers, employee_id):
    template = create_template(client, hr_headers, "T1").json()
    create_rule(client, hr_headers, "All", [template["id"]])

    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)
    second = client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)

    assert second.json()["assigned_count"] == 0
    assert second.json()["skipped_existing"] == ["T1"]


def test_employee_cannot_run_assignment(client, employee_login, employee_id):
    assert client.post(
        f"{API}/employees/{employee_id}/assign-tasks", headers=employee_login
    ).status_code == 403


# --- Employee task interaction ---------------------------------------------


def test_employee_sees_and_completes_their_own_tasks(client, hr_headers, employee_login, employee_id):
    template = create_template(client, hr_headers, "T1", title="Read the handbook").json()
    create_rule(client, hr_headers, "All", [template["id"]])
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)

    mine = client.get(f"{API}/my-tasks", headers=employee_login)
    assert mine.status_code == 200
    assert len(mine.json()) == 1
    task = mine.json()[0]

    done = client.patch(
        f"{API}/tasks/{task['id']}", json={"status": "completed"}, headers=employee_login
    )
    assert done.status_code == 200
    assert done.json()["status"] == "completed"
    assert done.json()["completed_at"] is not None


def test_employee_cannot_see_another_employees_tasks(client, hr_headers, employee_login):
    other = client.post(
        f"{API}/employees",
        json={"first_name": "Rohit", "last_name": "Verma",
              "work_email": "rohit.tasks@example.com"},
        headers=hr_headers,
    ).json()

    assert client.get(
        f"{API}/employees/{other['id']}/tasks", headers=employee_login
    ).status_code == 403


def test_employee_cannot_waive_a_task(client, hr_headers, employee_login, employee_id):
    template = create_template(client, hr_headers, "T1").json()
    create_rule(client, hr_headers, "All", [template["id"]])
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)
    task = client.get(f"{API}/my-tasks", headers=employee_login).json()[0]

    response = client.post(
        f"{API}/tasks/{task['id']}/waive",
        json={"reason": "I do not want to do this task at all"},
        headers=employee_login,
    )
    assert response.status_code == 403


def test_waiving_requires_a_reason(client, hr_headers, employee_id):
    template = create_template(client, hr_headers, "T1").json()
    create_rule(client, hr_headers, "All", [template["id"]])
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)
    task = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()[0]

    assert client.post(
        f"{API}/tasks/{task['id']}/waive", json={}, headers=hr_headers
    ).status_code == 422
    assert client.post(
        f"{API}/tasks/{task['id']}/waive", json={"reason": "n/a"}, headers=hr_headers
    ).status_code == 422

    ok = client.post(
        f"{API}/tasks/{task['id']}/waive",
        json={"reason": "Employee transferred from another group company."},
        headers=hr_headers,
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "waived"
    assert "transferred" in ok.json()["waiver_reason"]


def test_status_endpoint_refuses_to_waive_without_a_reason(client, hr_headers, employee_id):
    """The generic status endpoint must not become a back door around the reason."""
    template = create_template(client, hr_headers, "T1").json()
    create_rule(client, hr_headers, "All", [template["id"]])
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)
    task = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()[0]

    response = client.patch(
        f"{API}/tasks/{task['id']}", json={"status": "waived"}, headers=hr_headers
    )
    assert response.status_code == 422


def test_reopening_a_task_clears_its_completion_record(client, hr_headers, employee_id):
    template = create_template(client, hr_headers, "T1").json()
    create_rule(client, hr_headers, "All", [template["id"]])
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)
    task = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()[0]

    client.patch(f"{API}/tasks/{task['id']}", json={"status": "completed"}, headers=hr_headers)
    reopened = client.patch(
        f"{API}/tasks/{task['id']}", json={"status": "pending"}, headers=hr_headers
    )
    assert reopened.json()["status"] == "pending"
    assert reopened.json()["completed_at"] is None


def test_hr_can_add_a_one_off_task(client, hr_headers, employee_id):
    response = client.post(
        f"{API}/employees/{employee_id}/tasks",
        json={"title": "Return the old access card", "is_mandatory": True},
        headers=hr_headers,
    )
    assert response.status_code == 201
    assert response.json()["template_id"] is None
    assert response.json()["title"] == "Return the old access card"


def test_progress_endpoint(client, hr_headers, employee_id):
    templates = [create_template(client, hr_headers, f"T{i}").json() for i in range(4)]
    create_rule(client, hr_headers, "All", [t["id"] for t in templates])
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)

    tasks = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()
    client.patch(f"{API}/tasks/{tasks[0]['id']}", json={"status": "completed"},
                 headers=hr_headers)

    progress = client.get(
        f"{API}/employees/{employee_id}/task-progress", headers=hr_headers
    ).json()
    assert progress["total"] == 4
    assert progress["completed"] == 1
    assert progress["percent_complete"] == 25
    assert progress["all_mandatory_done"] is False


def test_task_actions_are_audited(client, hr_headers, employee_id, db):
    template = create_template(client, hr_headers, "T1").json()
    create_rule(client, hr_headers, "All", [template["id"]])
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)
    task = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()[0]
    client.patch(f"{API}/tasks/{task['id']}", json={"status": "completed"}, headers=hr_headers)

    actions = {row.action for row in db.scalars(select(AuditLog)).all()}
    assert AuditAction.TASKS_ASSIGNED.value in actions
    assert AuditAction.TASK_COMPLETED.value in actions


# --- Document checklist ----------------------------------------------------


def test_checklist_item_completes_when_the_document_is_approved(
    client, hr_headers, employee_id
):
    """The system already knows the answer — it should not ask anyone to tick a box."""
    template = create_template(
        client, hr_headers, "DOC_AADHAAR", title="Submit Aadhaar",
        category="document_checklist", required_document_type="aadhaar",
    ).json()
    create_rule(client, hr_headers, "All", [template["id"]])
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)

    task = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()[0]
    assert task["status"] == "pending"

    document = upload_file(
        client, hr_headers, employee_id,
        data=make_text_pdf(AADHAAR_TEXT), filename="aadhaar.pdf",
        document_type="aadhaar", content_type="application/pdf",
    ).json()
    client.post(f"{API}/documents/{document['id']}/approve", json={}, headers=hr_headers)

    refreshed = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()[0]
    assert refreshed["status"] == "completed"
    assert "automatically" in (refreshed["notes"] or "")


def test_checklist_item_stays_open_while_the_document_is_only_uploaded(
    client, hr_headers, employee_id
):
    """Uploading is not approval — the item must not close early."""
    template = create_template(
        client, hr_headers, "DOC_AADHAAR", category="document_checklist",
        required_document_type="aadhaar",
    ).json()
    create_rule(client, hr_headers, "All", [template["id"]])
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)

    upload_file(
        client, hr_headers, employee_id,
        data=make_text_pdf(AADHAAR_TEXT), filename="aadhaar.pdf",
        document_type="aadhaar", content_type="application/pdf",
    )

    task = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()[0]
    assert task["status"] == "pending"


def test_a_document_approved_before_assignment_still_closes_the_item(
    client, hr_headers, employee_id
):
    document = upload_file(
        client, hr_headers, employee_id,
        data=make_text_pdf(AADHAAR_TEXT), filename="aadhaar.pdf",
        document_type="aadhaar", content_type="application/pdf",
    ).json()
    client.post(f"{API}/documents/{document['id']}/approve", json={}, headers=hr_headers)

    template = create_template(
        client, hr_headers, "DOC_AADHAAR", category="document_checklist",
        required_document_type="aadhaar",
    ).json()
    create_rule(client, hr_headers, "All", [template["id"]])
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)

    task = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()[0]
    assert task["status"] == "completed"
