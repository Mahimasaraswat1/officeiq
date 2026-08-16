"""Audit-log filtering and the self-service profile surface (PRD A.7.9 / A.7.10)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.core.security import utcnow
from app.models.audit import AuditLog
from app.models.enums import AuditAction
from app.models.user import RefreshToken, User
from tests.conftest import ADMIN, API, HR, auth_headers

EMPLOYEE = {
    "first_name": "Ananya",
    "last_name": "Sharma",
    "work_email": "ananya.audit@example.com",
    "department": "Engineering",
}


# --- Audit filtering -------------------------------------------------------


def test_audit_is_admin_only(client, hr_headers):
    assert client.get(f"{API}/audit-logs", headers=hr_headers).status_code == 403
    assert client.get(f"{API}/audit-logs/facets", headers=hr_headers).status_code == 403
    assert client.get(f"{API}/audit-logs").status_code == 401


def test_filter_by_action(client, admin_headers, hr_headers):
    client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)

    body = client.get(
        f"{API}/audit-logs", headers=admin_headers, params={"action": "employee_created"}
    ).json()

    assert body["total"] >= 1
    assert {item["action"] for item in body["items"]} == {"employee_created"}


def test_filter_by_actor_is_a_substring_match(client, admin_headers, hr_headers):
    client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)

    body = client.get(
        f"{API}/audit-logs", headers=admin_headers, params={"actor": "hr@exam"}
    ).json()

    assert body["total"] >= 1
    assert all(item["actor_email"] == HR["email"] for item in body["items"])


def test_filter_by_entity(client, admin_headers, hr_headers):
    employee_id = client.post(
        f"{API}/employees", json=EMPLOYEE, headers=hr_headers
    ).json()["id"]

    body = client.get(
        f"{API}/audit-logs",
        headers=admin_headers,
        params={"entity_type": "employee", "entity_id": employee_id},
    ).json()

    assert body["total"] >= 1
    assert all(item["entity_id"] == employee_id for item in body["items"])


def test_date_range_includes_the_whole_end_day(client, admin_headers, hr_headers):
    """A range ending 'today' must include entries written later today."""
    client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)
    today = date.today()

    body = client.get(
        f"{API}/audit-logs",
        headers=admin_headers,
        params={"date_from": today.isoformat(), "date_to": today.isoformat()},
    ).json()
    assert body["total"] >= 1

    yesterday = (today - timedelta(days=1)).isoformat()
    empty = client.get(
        f"{API}/audit-logs",
        headers=admin_headers,
        params={"date_from": yesterday, "date_to": yesterday},
    ).json()
    assert empty["total"] == 0


def test_facets_come_from_recorded_data(client, admin_headers, hr_headers):
    client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)

    facets = client.get(f"{API}/audit-logs/facets", headers=admin_headers).json()

    assert "employee_created" in facets["actions"]
    assert "employee" in facets["entity_types"]
    assert HR["email"] in facets["actors"]
    assert facets["total"] >= 1
    # Only actions that actually happened are offered — no dead dropdown options.
    assert "task_waived" not in facets["actions"]


def test_single_entry_lookup(client, admin_headers, hr_headers):
    client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)
    first = client.get(f"{API}/audit-logs", headers=admin_headers).json()["items"][0]

    entry = client.get(f"{API}/audit-logs/{first['id']}", headers=admin_headers)
    assert entry.status_code == 200
    assert entry.json()["id"] == first["id"]

    assert client.get(
        f"{API}/audit-logs/{uuid.uuid4()}", headers=admin_headers
    ).status_code == 404


def test_login_failures_are_recorded_against_the_attempted_email(client, admin_headers):
    client.post(
        f"{API}/auth/login", json={"email": "nobody@example.com", "password": "Wrong@123"}
    )

    body = client.get(
        f"{API}/audit-logs", headers=admin_headers, params={"action": "login_failed"}
    ).json()

    assert body["total"] == 1
    assert body["items"][0]["actor_email"] == "nobody@example.com"
    assert body["items"][0]["detail"]["reason"] == "unknown_email"


# --- Sessions --------------------------------------------------------------


def test_signing_in_records_a_session_with_its_device(client, hr_user):
    client.post(
        f"{API}/auth/login",
        json={"email": HR["email"], "password": HR["password"]},
        headers={"User-Agent": "OfficeIQ-Test/1.0"},
    )
    headers = auth_headers(client, HR["email"], HR["password"])

    sessions = client.get(f"{API}/profile/sessions", headers=headers).json()
    assert len(sessions) == 2
    assert any(s["user_agent"] == "OfficeIQ-Test/1.0" for s in sessions)
    assert all(s["last_used_at"] is not None for s in sessions)


def test_refreshing_updates_last_used(client, hr_user, db):
    tokens = client.post(
        f"{API}/auth/login", json={"email": HR["email"], "password": HR["password"]}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    stored = db.scalar(select(RefreshToken))
    stored.last_used_at = utcnow() - timedelta(days=3)
    db.commit()
    before = stored.last_used_at

    client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    db.expire_all()
    assert db.scalar(select(RefreshToken)).last_used_at > before


def test_revoked_and_expired_sessions_are_not_listed(client, hr_user, db, hr_headers):
    stored = db.scalar(select(RefreshToken))
    stored.revoked_at = utcnow()
    db.commit()

    assert client.get(f"{API}/profile/sessions", headers=hr_headers).json() == []


def test_revoking_one_session_kills_only_that_one(client, hr_user, db):
    credentials = {"email": HR["email"], "password": HR["password"]}
    # Distinct user agents, because two logins in the same second share a
    # created_at and "the older one" would be ambiguous.
    laptop = client.post(
        f"{API}/auth/login", json=credentials, headers={"User-Agent": "Laptop/1.0"}
    ).json()
    phone = client.post(
        f"{API}/auth/login", json=credentials, headers={"User-Agent": "Phone/1.0"}
    ).json()
    headers = {"Authorization": f"Bearer {phone['access_token']}"}

    sessions = client.get(f"{API}/profile/sessions", headers=headers)
    assert len(sessions.json()) == 2

    laptop_session = next(s for s in sessions.json() if s["user_agent"] == "Laptop/1.0")
    assert client.delete(
        f"{API}/profile/sessions/{laptop_session['id']}", headers=headers
    ).status_code == 200

    remaining = client.get(f"{API}/profile/sessions", headers=headers).json()
    assert [s["user_agent"] for s in remaining] == ["Phone/1.0"]

    # The surviving device keeps working; the revoked one cannot refresh.
    assert client.post(
        f"{API}/auth/refresh", json={"refresh_token": phone["refresh_token"]}
    ).status_code == 200
    assert client.post(
        f"{API}/auth/refresh", json={"refresh_token": laptop["refresh_token"]}
    ).status_code == 401


def test_cannot_revoke_someone_elses_session(client, hr_user, admin_user, hr_headers, admin_headers):
    session_id = client.get(f"{API}/profile/sessions", headers=hr_headers).json()[0]["id"]

    # Indistinguishable from a nonexistent id, so it confirms nothing.
    response = client.delete(f"{API}/profile/sessions/{session_id}", headers=admin_headers)
    assert response.status_code == 404
    assert len(client.get(f"{API}/profile/sessions", headers=hr_headers).json()) == 1


def test_revoke_all_signs_every_device_out(client, hr_user, db):
    client.post(f"{API}/auth/login", json={"email": HR["email"], "password": HR["password"]})
    tokens = client.post(
        f"{API}/auth/login", json={"email": HR["email"], "password": HR["password"]}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    response = client.post(f"{API}/profile/sessions/revoke-all", headers=headers)
    assert response.status_code == 200
    assert "2 device(s)" in response.json()["message"]

    assert client.get(f"{API}/profile/sessions", headers=headers).json() == []
    assert client.post(
        f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    ).status_code == 401


def test_revoking_is_audited(client, hr_user, db, hr_headers):
    session_id = client.get(f"{API}/profile/sessions", headers=hr_headers).json()[0]["id"]
    client.delete(f"{API}/profile/sessions/{session_id}", headers=hr_headers)

    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.SESSION_REVOKED.value)
    )
    assert entry is not None
    assert entry.detail["scope"] == "single"


def test_revoke_all_on_a_single_session_is_not_an_error(client, hr_headers):
    response = client.post(f"{API}/profile/sessions/revoke-all", headers=hr_headers)
    assert response.status_code == 200
    assert "1 device(s)" in response.json()["message"]


def test_sessions_require_authentication(client):
    assert client.get(f"{API}/profile/sessions").status_code == 401
    assert client.post(f"{API}/profile/sessions/revoke-all").status_code == 401


# --- Personal activity -----------------------------------------------------


def test_activity_shows_my_own_actions_only(client, hr_headers, admin_headers):
    client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)

    hr_activity = client.get(f"{API}/profile/activity", headers=hr_headers).json()
    admin_activity = client.get(f"{API}/profile/activity", headers=admin_headers).json()

    assert "employee_created" in {entry["action"] for entry in hr_activity}
    # The Admin did not create that employee, so it is not their activity —
    # /audit-logs is where an Admin reads everyone's.
    assert "employee_created" not in {entry["action"] for entry in admin_activity}


def test_activity_is_newest_first_and_capped(client, hr_headers):
    for index in range(4):
        client.patch(
            f"{API}/profile", json={"full_name": f"Priya {index}"}, headers=hr_headers
        )

    entries = client.get(
        f"{API}/profile/activity", headers=hr_headers, params={"limit": 3}
    ).json()

    assert len(entries) == 3
    stamps = [entry["created_at"] for entry in entries]
    assert stamps == sorted(stamps, reverse=True)


def test_activity_limit_is_bounded(client, hr_headers):
    assert client.get(
        f"{API}/profile/activity", headers=hr_headers, params={"limit": 500}
    ).status_code == 422


def test_changing_a_password_ends_other_sessions(client, hr_user, db):
    other = client.post(
        f"{API}/auth/login", json={"email": HR["email"], "password": HR["password"]}
    ).json()
    headers = auth_headers(client, HR["email"], HR["password"])

    response = client.post(
        f"{API}/profile/password",
        json={"current_password": HR["password"], "new_password": "BrandNew@456"},
        headers=headers,
    )
    assert response.status_code == 200

    assert client.get(f"{API}/profile/sessions", headers=headers).json() == []
    assert client.post(
        f"{API}/auth/refresh", json={"refresh_token": other["refresh_token"]}
    ).status_code == 401
