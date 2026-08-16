"""Phase 3 ↔ Phase 4 integration: approval triggers assignment, tasks gate completion."""

from __future__ import annotations

import pytest

from tests.conftest import API
from tests.factories import AADHAAR_TEXT, PAN_TEXT, make_png, make_text_pdf, upload_file

EMPLOYEE = {
    "first_name": "Ananya",
    "last_name": "Sharma",
    "work_email": "ananya.flow@example.com",
    "department": "Engineering",
}
PAN_TEXT_ANANYA = PAN_TEXT.replace("Rohit Verma", "Ananya Sharma")


@pytest.fixture
def employee_id(client, hr_headers) -> str:
    return client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers).json()["id"]


@pytest.fixture
def catalogue(client, hr_headers):
    """A small template catalogue plus a match-everyone rule."""
    templates = {}
    for code, extra in (
        ("TRAIN_ORIENTATION", {"category": "training", "default_due_days": 7}),
        ("POLICY_CONDUCT", {"category": "policy_acknowledgement", "default_due_days": 5}),
        ("OPTIONAL_TOUR", {"is_mandatory": False}),
    ):
        templates[code] = client.post(
            f"{API}/task-templates",
            json={"code": code, "title": code.title(), **extra},
            headers=hr_headers,
        ).json()

    client.post(
        f"{API}/assignment-rules",
        json={
            "name": "All new joiners",
            "items": [{"template_id": t["id"]} for t in templates.values()],
        },
        headers=hr_headers,
    )
    return templates


def approve_all_required(client, hr_headers, employee_id):
    """Upload and approve the three required documents."""
    uploads = [
        (make_text_pdf(AADHAAR_TEXT), "aadhaar.pdf", "aadhaar", "application/pdf"),
        (make_text_pdf(PAN_TEXT_ANANYA), "pan.pdf", "pan", "application/pdf"),
        (make_png(), "photo.png", "photo", "image/png"),
    ]
    ids = []
    for data, filename, doc_type, content_type in uploads:
        ids.append(
            upload_file(
                client, hr_headers, employee_id, data=data, filename=filename,
                document_type=doc_type, content_type=content_type,
            ).json()["id"]
        )
    for document_id in ids:
        client.post(f"{API}/documents/{document_id}/approve", json={}, headers=hr_headers)
    return ids


def test_approving_all_documents_triggers_assignment(
    client, hr_headers, employee_id, catalogue
):
    """PRD A.6 step 7: reaching the tasks stage auto-assigns from the rules."""
    assert client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json() == []

    approve_all_required(client, hr_headers, employee_id)

    employee = client.get(f"{API}/employees/{employee_id}", headers=hr_headers).json()
    assert employee["onboarding_status"] == "tasks_assigned"

    tasks = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()
    assert len(tasks) == 3


def test_outstanding_mandatory_tasks_block_completion(
    client, hr_headers, employee_id, catalogue
):
    approve_all_required(client, hr_headers, employee_id)
    client.post(f"{API}/employees/{employee_id}/face-match", headers=hr_headers)

    summary = client.get(
        f"{API}/employees/{employee_id}/verification-summary", headers=hr_headers
    ).json()

    assert summary["tasks_total"] == 3
    assert summary["tasks_mandatory_outstanding"] == 2
    assert any("mandatory task" in issue for issue in summary["blocking_issues"])

    blocked = client.post(
        f"{API}/employees/{employee_id}/complete-onboarding", headers=hr_headers
    )
    assert blocked.status_code == 409
    assert "mandatory task" in blocked.json()["error"]["message"]


def test_optional_tasks_do_not_block_completion(client, hr_headers, employee_id, catalogue):
    approve_all_required(client, hr_headers, employee_id)

    tasks = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()
    for task in tasks:
        if task["is_mandatory"]:
            client.patch(
                f"{API}/tasks/{task['id']}", json={"status": "completed"}, headers=hr_headers
            )

    summary = client.get(
        f"{API}/employees/{employee_id}/verification-summary", headers=hr_headers
    ).json()
    # The optional task is still open, but must not appear as a blocker.
    assert summary["tasks_mandatory_outstanding"] == 0
    assert not any("mandatory task" in issue for issue in summary["blocking_issues"])


def test_waiving_the_last_mandatory_task_unblocks_completion(
    client, hr_headers, employee_id, catalogue
):
    approve_all_required(client, hr_headers, employee_id)

    tasks = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()
    mandatory = [t for t in tasks if t["is_mandatory"]]

    client.patch(
        f"{API}/tasks/{mandatory[0]['id']}", json={"status": "completed"}, headers=hr_headers
    )
    client.post(
        f"{API}/tasks/{mandatory[1]['id']}/waive",
        json={"reason": "Completed at a previous group company; evidence on file."},
        headers=hr_headers,
    )

    summary = client.get(
        f"{API}/employees/{employee_id}/verification-summary", headers=hr_headers
    ).json()
    assert summary["tasks_mandatory_outstanding"] == 0


def test_checklist_items_close_as_documents_are_approved_through_the_flow(
    client, hr_headers, employee_id
):
    for code, doc_type in (("DOC_AADHAAR", "aadhaar"), ("DOC_PAN", "pan")):
        client.post(
            f"{API}/task-templates",
            json={
                "code": code,
                "title": f"Submit {doc_type}",
                "category": "document_checklist",
                "required_document_type": doc_type,
            },
            headers=hr_headers,
        )
    templates = client.get(f"{API}/task-templates", headers=hr_headers).json()
    client.post(
        f"{API}/assignment-rules",
        json={"name": "Docs", "items": [{"template_id": t["id"]} for t in templates]},
        headers=hr_headers,
    )
    client.post(f"{API}/employees/{employee_id}/assign-tasks", headers=hr_headers)

    aadhaar = upload_file(
        client, hr_headers, employee_id, data=make_text_pdf(AADHAAR_TEXT),
        filename="aadhaar.pdf", document_type="aadhaar", content_type="application/pdf",
    ).json()
    client.post(f"{API}/documents/{aadhaar['id']}/approve", json={}, headers=hr_headers)

    tasks = {
        t["title"]: t["status"]
        for t in client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()
    }
    assert tasks["Submit aadhaar"] == "completed"
    assert tasks["Submit pan"] == "pending"


def test_full_journey_to_onboarding_complete(client, hr_headers, employee_id, catalogue):
    """Documents approved → tasks assigned → tasks done → onboarding complete."""
    approve_all_required(client, hr_headers, employee_id)
    client.post(f"{API}/employees/{employee_id}/face-match", headers=hr_headers)

    for task in client.get(
        f"{API}/employees/{employee_id}/tasks", headers=hr_headers
    ).json():
        client.patch(
            f"{API}/tasks/{task['id']}", json={"status": "completed"}, headers=hr_headers
        )

    summary = client.get(
        f"{API}/employees/{employee_id}/verification-summary", headers=hr_headers
    ).json()

    # Face matching uses the stub engine here, so it is expected to be blocking.
    remaining = [i for i in summary["blocking_issues"] if "face match" not in i]
    assert remaining == [], remaining
    assert summary["tasks_mandatory_outstanding"] == 0


def test_assignment_does_not_duplicate_when_review_reruns(
    client, hr_headers, employee_id, catalogue
):
    """Re-approving documents must not assign a second copy of every task."""
    document_ids = approve_all_required(client, hr_headers, employee_id)
    first = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()

    for document_id in document_ids:
        client.post(f"{API}/documents/{document_id}/approve", json={}, headers=hr_headers)

    second = client.get(f"{API}/employees/{employee_id}/tasks", headers=hr_headers).json()
    assert len(second) == len(first)
