"""HR review workflow: verification, approve/reject, and status transitions."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.enums import AuditAction
from tests.conftest import API
from tests.factories import (
    AADHAAR_TEXT,
    PAN_TEXT,
    VALID_AADHAAR,
    make_png,
    make_text_pdf,
    upload_file,
)

EMPLOYEE = {
    "first_name": "Ananya",
    "last_name": "Sharma",
    "work_email": "ananya.sharma@example.com",
}

# A structurally valid number that the mock registry always rejects.
RESERVED_FAILING = "999999990019"

# The shared PAN fixture names Rohit Verma; most tests here use an employee
# named Ananya Sharma, so re-point the name to avoid an unintended mismatch.
PAN_TEXT_ANANYA = PAN_TEXT.replace("Rohit Verma", "Ananya Sharma")


@pytest.fixture
def employee_id(client, hr_headers) -> str:
    return client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers).json()["id"]


def upload_pdf(client, headers, employee_id, text, document_type):
    return upload_file(
        client, headers, employee_id,
        data=make_text_pdf(text), filename=f"{document_type}.pdf",
        document_type=document_type, content_type="application/pdf",
    )


def upload_photo(client, headers, employee_id):
    return upload_file(
        client, headers, employee_id,
        data=make_png(), filename="photo.png", document_type="photo",
    )


# --- Automatic verification after extraction -------------------------------


def test_verification_runs_automatically_after_upload(client, hr_headers, employee_id):
    upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar")

    checks = client.get(
        f"{API}/employees/{employee_id}/verifications", headers=hr_headers
    ).json()
    assert len(checks) == 1
    assert checks[0]["check_type"] == "aadhaar"
    assert checks[0]["status"] == "passed"
    assert checks[0]["provider"] == "mock-uidai-nsdl"


def test_full_aadhaar_number_is_never_stored_or_returned(
    client, hr_headers, employee_id
):
    upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar")

    check = client.get(
        f"{API}/employees/{employee_id}/verifications", headers=hr_headers
    ).json()[0]

    assert check["masked_number"] == "XXXX XXXX 2346"
    # The raw number must not appear anywhere in the verification payload.
    assert VALID_AADHAAR not in str(check)


def test_pan_verification_runs_automatically(client, hr_headers, employee_id):
    upload_pdf(client, hr_headers, employee_id, PAN_TEXT_ANANYA, "pan")

    checks = client.get(
        f"{API}/employees/{employee_id}/verifications", headers=hr_headers
    ).json()
    assert checks[0]["check_type"] == "pan"
    assert checks[0]["status"] == "passed"


def test_name_mismatch_fails_verification_even_with_a_valid_number(
    client, hr_headers
):
    """An ID that verifies but belongs to someone else must not pass."""
    other = client.post(
        f"{API}/employees",
        json={
            "first_name": "Rohit",
            "last_name": "Verma",
            "work_email": "rohit.verma@example.com",
        },
        headers=hr_headers,
    ).json()

    # The Aadhaar document names Ananya Sharma, but this profile is Rohit Verma.
    upload_pdf(client, hr_headers, other["id"], AADHAAR_TEXT, "aadhaar")

    check = client.get(
        f"{API}/employees/{other['id']}/verifications", headers=hr_headers
    ).json()[0]

    assert check["status"] == "failed"
    assert check["reason_code"] == "name_mismatch"
    assert check["detail"]["name_matches"] is False


def test_checksum_failure_surfaces_to_hr(client, hr_headers, employee_id):
    bad = AADHAAR_TEXT.replace("2341 2341 2346", "2341 2341 2345")
    upload_pdf(client, hr_headers, employee_id, bad, "aadhaar")

    check = client.get(
        f"{API}/employees/{employee_id}/verifications", headers=hr_headers
    ).json()[0]
    assert check["status"] == "failed"
    assert check["reason_code"] == "checksum_failed"


def test_registry_rejection_path(client, hr_headers, employee_id):
    text = AADHAAR_TEXT.replace(
        "2341 2341 2346", f"{RESERVED_FAILING[:4]} {RESERVED_FAILING[4:8]} {RESERVED_FAILING[8:]}"
    )
    upload_pdf(client, hr_headers, employee_id, text, "aadhaar")

    check = client.get(
        f"{API}/employees/{employee_id}/verifications", headers=hr_headers
    ).json()[0]
    assert check["reason_code"] == "not_found_in_registry"


def test_verification_is_audited(client, hr_headers, employee_id, db):
    upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar")

    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.ID_VERIFICATION_RUN.value)
    )
    assert entry is not None
    assert entry.detail["check_type"] == "aadhaar"
    assert VALID_AADHAAR not in str(entry.detail)


# --- Manual verification ---------------------------------------------------


def test_hr_can_rerun_verification(client, hr_headers, employee_id):
    doc = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()

    response = client.post(f"{API}/documents/{doc['id']}/verify", headers=hr_headers)
    assert response.status_code == 201

    # History is kept rather than overwritten.
    checks = client.get(
        f"{API}/employees/{employee_id}/verifications", headers=hr_headers
    ).json()
    assert len(checks) == 2


def test_verifying_a_non_id_document_is_rejected(client, hr_headers, employee_id):
    photo = upload_photo(client, hr_headers, employee_id).json()
    response = client.post(f"{API}/documents/{photo['id']}/verify", headers=hr_headers)
    assert response.status_code == 422


def test_employee_cannot_run_verification(client, hr_headers, employee_id, db):
    from app.core.security import hash_password
    from app.models.enums import UserRole
    from app.models.user import User
    from tests.conftest import auth_headers

    db.add(
        User(
            email="staffer@example.com",
            hashed_password=hash_password("Staffer@123"),
            full_name="Staffer",
            role=UserRole.EMPLOYEE,
        )
    )
    db.commit()
    headers = auth_headers(client, "staffer@example.com", "Staffer@123")

    doc = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    assert client.post(f"{API}/documents/{doc['id']}/verify", headers=headers).status_code == 403


# --- Approve / reject ------------------------------------------------------


def test_hr_can_approve_a_document(client, hr_headers, employee_id):
    doc = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()

    response = client.post(
        f"{API}/documents/{doc['id']}/approve", json={}, headers=hr_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["reviewed_at"] is not None


def test_rejection_requires_a_reason(client, hr_headers, employee_id):
    doc = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()

    # Missing entirely.
    assert client.post(
        f"{API}/documents/{doc['id']}/reject", json={}, headers=hr_headers
    ).status_code == 422

    # Present but too short to be useful to the employee.
    response = client.post(
        f"{API}/documents/{doc['id']}/reject", json={"reason": "bad"}, headers=hr_headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

    # Whitespace padding must not satisfy the minimum length.
    assert client.post(
        f"{API}/documents/{doc['id']}/reject",
        json={"reason": "   x      "},
        headers=hr_headers,
    ).status_code == 422


def test_rejection_with_a_reason_succeeds_and_is_stored(client, hr_headers, employee_id):
    doc = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    reason = "The scan is too blurry to read the Aadhaar number. Please re-upload."

    response = client.post(
        f"{API}/documents/{doc['id']}/reject", json={"reason": reason}, headers=hr_headers
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["rejection_reason"] == reason

    detail = client.get(f"{API}/documents/{doc['id']}", headers=hr_headers).json()
    assert detail["rejection_reason"] == reason
    assert detail["reviewed_by_id"] is not None


def test_employee_sees_the_rejection_reason(client, hr_headers, employee_id, db):
    """The employee must be told what to fix."""
    import re
    from pathlib import Path

    from app.core.config import settings

    doc = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    reason = "The document is expired. Please upload a current Aadhaar card."
    client.post(
        f"{API}/documents/{doc['id']}/reject", json={"reason": reason}, headers=hr_headers
    )

    files = sorted(Path(settings.EMAIL_OUTBOX_DIR).glob("*.txt"))
    token = re.search(r"accept-invite\?token=([A-Za-z0-9_\-]+)", files[-1].read_text()).group(1)
    client.post(f"{API}/onboarding/accept", json={"token": token, "password": "Ananya@12345"})
    tokens = client.post(
        f"{API}/auth/login",
        json={"email": EMPLOYEE["work_email"], "password": "Ananya@12345"},
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    detail = client.get(f"{API}/documents/{doc['id']}", headers=headers).json()
    assert detail["rejection_reason"] == reason


def test_employee_cannot_approve_or_reject(client, hr_headers, employee_id, db):
    from app.core.security import hash_password
    from app.models.enums import UserRole
    from app.models.user import User
    from tests.conftest import auth_headers

    db.add(
        User(
            email="staffer@example.com",
            hashed_password=hash_password("Staffer@123"),
            full_name="Staffer",
            role=UserRole.EMPLOYEE,
        )
    )
    db.commit()
    headers = auth_headers(client, "staffer@example.com", "Staffer@123")

    doc = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()

    assert client.post(
        f"{API}/documents/{doc['id']}/approve", json={}, headers=headers
    ).status_code == 403
    assert client.post(
        f"{API}/documents/{doc['id']}/reject",
        json={"reason": "Not acceptable for review purposes."},
        headers=headers,
    ).status_code == 403


def test_approval_and_rejection_are_audited(client, hr_headers, employee_id, db):
    first = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    second = upload_pdf(client, hr_headers, employee_id, PAN_TEXT_ANANYA, "pan").json()

    client.post(f"{API}/documents/{first['id']}/approve", json={}, headers=hr_headers)
    client.post(
        f"{API}/documents/{second['id']}/reject",
        json={"reason": "The PAN card image is cropped and unreadable."},
        headers=hr_headers,
    )

    actions = {row.action for row in db.scalars(select(AuditLog)).all()}
    assert AuditAction.DOCUMENT_APPROVED.value in actions
    assert AuditAction.DOCUMENT_REJECTED.value in actions

    rejection = db.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.DOCUMENT_REJECTED.value)
    )
    assert "cropped" in rejection.detail["reason"]


# --- Onboarding status transitions -----------------------------------------


def test_status_advances_to_under_review_once_all_documents_are_in(
    client, hr_headers, employee_id
):
    upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar")
    upload_pdf(client, hr_headers, employee_id, PAN_TEXT_ANANYA, "pan")
    upload_photo(client, hr_headers, employee_id)

    employee = client.get(f"{API}/employees/{employee_id}", headers=hr_headers).json()
    assert employee["onboarding_status"] == "under_review"


def test_status_advances_to_tasks_assigned_when_all_required_are_approved(
    client, hr_headers, employee_id
):
    ids = [
        upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()["id"],
        upload_pdf(client, hr_headers, employee_id, PAN_TEXT_ANANYA, "pan").json()["id"],
        upload_photo(client, hr_headers, employee_id).json()["id"],
    ]
    for document_id in ids:
        client.post(f"{API}/documents/{document_id}/approve", json={}, headers=hr_headers)

    employee = client.get(f"{API}/employees/{employee_id}", headers=hr_headers).json()
    assert employee["onboarding_status"] == "tasks_assigned"


def test_status_never_moves_backwards(client, hr_headers, employee_id):
    upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar")
    upload_pdf(client, hr_headers, employee_id, PAN_TEXT_ANANYA, "pan")
    upload_photo(client, hr_headers, employee_id)
    assert (
        client.get(f"{API}/employees/{employee_id}", headers=hr_headers).json()[
            "onboarding_status"
        ]
        == "under_review"
    )

    # Uploading another document must not rewind the stage.
    upload_pdf(client, hr_headers, employee_id, PAN_TEXT_ANANYA, "certificate")
    assert (
        client.get(f"{API}/employees/{employee_id}", headers=hr_headers).json()[
            "onboarding_status"
        ]
        == "under_review"
    )


def test_status_changes_are_audited(client, hr_headers, employee_id, db):
    upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar")

    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == AuditAction.ONBOARDING_STATUS_CHANGED.value
        )
    )
    assert entry is not None
    assert entry.detail["to"] in ("documents_submitted", "under_review")


# --- Verification summary --------------------------------------------------


def test_summary_lists_blocking_issues(client, hr_headers, employee_id):
    upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar")

    summary = client.get(
        f"{API}/employees/{employee_id}/verification-summary", headers=hr_headers
    ).json()

    assert summary["ready_for_completion"] is False
    assert "pan" in summary["missing_document_types"]
    assert "photo" in summary["missing_document_types"]
    assert summary["blocking_issues"]


def test_summary_counts_documents_by_state(client, hr_headers, employee_id):
    first = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    upload_pdf(client, hr_headers, employee_id, PAN_TEXT_ANANYA, "pan")

    client.post(f"{API}/documents/{first['id']}/approve", json={}, headers=hr_headers)

    summary = client.get(
        f"{API}/employees/{employee_id}/verification-summary", headers=hr_headers
    ).json()
    assert summary["documents_total"] == 2
    assert summary["documents_approved"] == 1
    assert summary["documents_pending_review"] == 1


def test_completion_is_blocked_until_every_check_passes(
    client, hr_headers, employee_id
):
    upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar")

    response = client.post(
        f"{API}/employees/{employee_id}/complete-onboarding", headers=hr_headers
    )
    assert response.status_code == 409
    assert "cannot be completed" in response.json()["error"]["message"]


def test_employee_can_read_their_own_verification_summary(
    client, hr_headers, employee_id
):
    import re
    from pathlib import Path

    from app.core.config import settings

    upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar")

    files = sorted(Path(settings.EMAIL_OUTBOX_DIR).glob("*.txt"))
    token = re.search(r"accept-invite\?token=([A-Za-z0-9_\-]+)", files[-1].read_text()).group(1)
    client.post(f"{API}/onboarding/accept", json={"token": token, "password": "Ananya@12345"})
    tokens = client.post(
        f"{API}/auth/login",
        json={"email": EMPLOYEE["work_email"], "password": "Ananya@12345"},
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    response = client.get(
        f"{API}/employees/{employee_id}/verification-summary", headers=headers
    )
    assert response.status_code == 200


def test_employee_cannot_read_another_employees_verifications(
    client, hr_headers, employee_id
):
    import re
    from pathlib import Path

    from app.core.config import settings

    other = client.post(
        f"{API}/employees",
        json={
            "first_name": "Rohit",
            "last_name": "Verma",
            "work_email": "rohit.verma@example.com",
        },
        headers=hr_headers,
    ).json()

    files = sorted(Path(settings.EMAIL_OUTBOX_DIR).glob("*.txt"))
    token = re.search(r"accept-invite\?token=([A-Za-z0-9_\-]+)", files[-1].read_text()).group(1)
    client.post(f"{API}/onboarding/accept", json={"token": token, "password": "Rohit@12345"})
    tokens = client.post(
        f"{API}/auth/login",
        json={"email": "rohit.verma@example.com", "password": "Rohit@12345"},
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert client.get(
        f"{API}/employees/{employee_id}/verifications", headers=headers
    ).status_code == 403
