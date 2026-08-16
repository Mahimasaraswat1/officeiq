"""End-to-end invitation flow: HR creates -> employee accepts -> employee signs in."""

from __future__ import annotations

import re
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.enums import AuditAction
from tests.conftest import API

EMPLOYEE = {
    "first_name": "Meera",
    "last_name": "Iyer",
    "work_email": "meera.iyer@example.com",
    "department": "Engineering",
    "designation": "QA Engineer",
}

TOKEN_RE = re.compile(r"accept-invite\?token=([A-Za-z0-9_\-]+)")


def latest_invite_token() -> str:
    files = sorted(Path(settings.EMAIL_OUTBOX_DIR).glob("*.txt"))
    assert files, "no invitation email was written to the outbox"
    match = TOKEN_RE.search(files[-1].read_text())
    assert match, "invite email did not contain a token link"
    return match.group(1)


def test_full_invitation_journey(client, hr_headers, db):
    created = client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)
    assert created.status_code == 201
    employee_id = created.json()["id"]

    token = latest_invite_token()

    preview = client.get(f"{API}/onboarding/invitation?token={token}")
    assert preview.status_code == 200
    assert preview.json()["email"] == EMPLOYEE["work_email"]
    assert preview.json()["first_name"] == "Meera"

    accepted = client.post(
        f"{API}/onboarding/accept",
        json={"token": token, "password": "Meera@12345", "phone": "9876543210"},
    )
    assert accepted.status_code == 200
    assert accepted.json()["user"]["role"] == "employee"
    assert accepted.json()["employee"]["onboarding_status"] == "registered"
    assert accepted.json()["employee"]["phone"] == "9876543210"

    signed_in = client.post(
        f"{API}/auth/login",
        json={"email": EMPLOYEE["work_email"], "password": "Meera@12345"},
    )
    assert signed_in.status_code == 200
    headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}

    own = client.get(f"{API}/employees/me", headers=headers)
    assert own.status_code == 200
    assert own.json()["id"] == employee_id

    accept_events = db.scalars(
        select(AuditLog).where(AuditLog.action == AuditAction.INVITATION_ACCEPTED.value)
    ).all()
    assert len(accept_events) == 1


def test_token_is_single_use(client, hr_headers):
    client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)
    token = latest_invite_token()

    first = client.post(
        f"{API}/onboarding/accept", json={"token": token, "password": "Meera@12345"}
    )
    assert first.status_code == 200

    replay = client.post(
        f"{API}/onboarding/accept", json={"token": token, "password": "Another@123"}
    )
    assert replay.status_code == 401


def test_invalid_token_is_rejected(client):
    response = client.get(f"{API}/onboarding/invitation?token={'x' * 40}")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_expired_token_is_rejected(client, hr_headers, db, monkeypatch):
    monkeypatch.setattr(settings, "INVITE_TOKEN_EXPIRE_HOURS", -1)
    client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)
    token = latest_invite_token()

    response = client.get(f"{API}/onboarding/invitation?token={token}")
    assert response.status_code == 401


def test_resending_an_invite_invalidates_the_previous_token(client, hr_headers):
    created = client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)
    old_token = latest_invite_token()

    resent = client.post(
        f"{API}/employees/{created.json()['id']}/invite", headers=hr_headers
    )
    assert resent.status_code == 201
    new_token = latest_invite_token()
    assert new_token != old_token

    assert client.get(f"{API}/onboarding/invitation?token={old_token}").status_code == 401
    assert client.get(f"{API}/onboarding/invitation?token={new_token}").status_code == 200


def test_revoked_invite_cannot_be_accepted(client, hr_headers):
    created = client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)
    token = latest_invite_token()

    revoked = client.post(
        f"{API}/employees/{created.json()['id']}/invite/revoke", headers=hr_headers
    )
    assert revoked.status_code == 200

    response = client.post(
        f"{API}/onboarding/accept", json={"token": token, "password": "Meera@12345"}
    )
    assert response.status_code == 401


def test_cannot_reinvite_a_registered_employee(client, hr_headers):
    created = client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)
    token = latest_invite_token()
    client.post(f"{API}/onboarding/accept", json={"token": token, "password": "Meera@12345"})

    response = client.post(
        f"{API}/employees/{created.json()['id']}/invite", headers=hr_headers
    )
    assert response.status_code == 409


def test_employee_cannot_read_another_employees_record(client, hr_headers):
    other = client.post(
        f"{API}/employees",
        json={**EMPLOYEE, "work_email": "someone.else@example.com"},
        headers=hr_headers,
    )
    client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)
    token = latest_invite_token()
    client.post(f"{API}/onboarding/accept", json={"token": token, "password": "Meera@12345"})

    signed_in = client.post(
        f"{API}/auth/login",
        json={"email": EMPLOYEE["work_email"], "password": "Meera@12345"},
    ).json()
    headers = {"Authorization": f"Bearer {signed_in['access_token']}"}

    response = client.get(f"{API}/employees/{other.json()['id']}", headers=headers)
    assert response.status_code == 403


def test_employee_can_update_own_allowed_fields(client, hr_headers):
    client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)
    token = latest_invite_token()
    client.post(f"{API}/onboarding/accept", json={"token": token, "password": "Meera@12345"})

    signed_in = client.post(
        f"{API}/auth/login",
        json={"email": EMPLOYEE["work_email"], "password": "Meera@12345"},
    ).json()
    headers = {"Authorization": f"Bearer {signed_in['access_token']}"}

    response = client.patch(
        f"{API}/employees/me", json={"city": "Bengaluru", "phone": "9000000000"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["city"] == "Bengaluru"

    # The self-update schema has no onboarding_status field, so it is ignored.
    escalate = client.patch(
        f"{API}/employees/me", json={"onboarding_status": "complete"}, headers=headers
    )
    assert escalate.status_code == 200
    assert escalate.json()["onboarding_status"] == "registered"
