"""Admin user management, self-service profile, and audit-log coverage."""

from __future__ import annotations

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.enums import AuditAction
from tests.conftest import ADMIN, API, HR

NEW_HR = {
    "email": "newhr@example.com",
    "full_name": "New HR",
    "password": "NewHr@12345",
    "role": "hr",
}


def test_admin_can_create_an_hr_user(client, admin_headers):
    response = client.post(f"{API}/users", json=NEW_HR, headers=admin_headers)
    assert response.status_code == 201
    assert response.json()["role"] == "hr"

    signed_in = client.post(
        f"{API}/auth/login",
        json={"email": NEW_HR["email"], "password": NEW_HR["password"]},
    )
    assert signed_in.status_code == 200


def test_hr_cannot_create_users(client, hr_headers):
    response = client.post(f"{API}/users", json=NEW_HR, headers=hr_headers)
    assert response.status_code == 403


def test_employee_role_cannot_be_created_directly(client, admin_headers):
    response = client.post(
        f"{API}/users", json={**NEW_HR, "role": "employee"}, headers=admin_headers
    )
    assert response.status_code == 409


def test_admin_cannot_deactivate_themselves(client, admin_headers, admin_user):
    response = client.patch(
        f"{API}/users/{admin_user.id}", json={"is_active": False}, headers=admin_headers
    )
    assert response.status_code == 409


def test_admin_cannot_demote_themselves(client, admin_headers, admin_user):
    response = client.patch(
        f"{API}/users/{admin_user.id}", json={"role": "hr"}, headers=admin_headers
    )
    assert response.status_code == 409


def test_user_list_supports_role_filter(client, admin_headers, hr_user):
    response = client.get(f"{API}/users?role=hr", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["email"] == HR["email"]


def test_profile_update_and_password_change(client, hr_headers):
    updated = client.patch(
        f"{API}/profile", json={"full_name": "Priya Nair"}, headers=hr_headers
    )
    assert updated.status_code == 200
    assert updated.json()["full_name"] == "Priya Nair"

    changed = client.post(
        f"{API}/profile/password",
        json={"current_password": HR["password"], "new_password": "Changed@1234"},
        headers=hr_headers,
    )
    assert changed.status_code == 200

    assert (
        client.post(
            f"{API}/auth/login", json={"email": HR["email"], "password": HR["password"]}
        ).status_code
        == 401
    )
    assert (
        client.post(
            f"{API}/auth/login", json={"email": HR["email"], "password": "Changed@1234"}
        ).status_code
        == 200
    )


def test_password_change_requires_the_current_password(client, hr_headers):
    response = client.post(
        f"{API}/profile/password",
        json={"current_password": "NotMyPassword1", "new_password": "Changed@1234"},
        headers=hr_headers,
    )
    assert response.status_code == 403


def test_audit_log_is_admin_only(client, hr_headers):
    assert client.get(f"{API}/audit-logs", headers=hr_headers).status_code == 403


def test_critical_actions_are_all_audited(client, admin_headers, hr_headers, db):
    client.post(
        f"{API}/employees",
        json={
            "first_name": "Ananya",
            "last_name": "Sharma",
            "work_email": "ananya@example.com",
        },
        headers=hr_headers,
    )

    recorded = {row.action for row in db.scalars(select(AuditLog)).all()}
    for expected in (
        AuditAction.LOGIN_SUCCESS,
        AuditAction.EMPLOYEE_CREATED,
        AuditAction.INVITATION_SENT,
    ):
        assert expected.value in recorded

    listing = client.get(f"{API}/audit-logs", headers=admin_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] >= 3


def test_audit_entries_capture_the_actor(client, hr_headers, db):
    client.post(
        f"{API}/employees",
        json={
            "first_name": "Ananya",
            "last_name": "Sharma",
            "work_email": "ananya@example.com",
        },
        headers=hr_headers,
    )
    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.EMPLOYEE_CREATED.value)
    )
    assert entry.actor_email == HR["email"]
    assert entry.actor_role == "hr"
    assert entry.entity_type == "employee"


def test_failed_login_is_audited_without_an_account(client, db):
    client.post(
        f"{API}/auth/login", json={"email": "ghost@example.com", "password": "Whatever1"}
    )
    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.LOGIN_FAILED.value)
    )
    assert entry is not None
    assert entry.actor_email == "ghost@example.com"
    assert entry.actor_user_id is None
