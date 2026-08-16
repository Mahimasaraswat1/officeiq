"""Auth: login, token expiry/refresh, lockout, access-denied paths (PRD B.4.1)."""

from __future__ import annotations

import jwt
from sqlalchemy import select

from app.core.config import settings
from app.core.security import decode_token
from app.models.audit import AuditLog
from app.models.enums import AuditAction
from tests.conftest import ADMIN, API, HR


def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_login_returns_token_pair_and_user(client, admin_user):
    response = client.post(
        f"{API}/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "admin"

    claims = decode_token(body["access_token"], "access")
    assert claims["sub"] == body["user"]["id"]
    assert claims["role"] == "admin"


def test_login_is_case_insensitive_on_email(client, admin_user):
    response = client.post(
        f"{API}/auth/login",
        json={"email": ADMIN["email"].upper(), "password": ADMIN["password"]},
    )
    assert response.status_code == 200


def test_login_with_wrong_password_uses_error_envelope(client, admin_user):
    response = client.post(
        f"{API}/auth/login", json={"email": ADMIN["email"], "password": "WrongPass1"}
    )
    assert response.status_code == 401
    body = response.json()
    assert body["status"] == 401
    assert body["error"]["code"] == "unauthenticated"


def test_unknown_email_and_wrong_password_are_indistinguishable(client, admin_user):
    unknown = client.post(
        f"{API}/auth/login", json={"email": "nobody@example.com", "password": "Whatever1"}
    )
    wrong = client.post(
        f"{API}/auth/login", json={"email": ADMIN["email"], "password": "WrongPass1"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


def test_account_locks_after_max_failed_attempts(client, admin_user, db):
    for _ in range(settings.MAX_FAILED_LOGIN_ATTEMPTS - 1):
        response = client.post(
            f"{API}/auth/login", json={"email": ADMIN["email"], "password": "WrongPass1"}
        )
        assert response.status_code == 401

    locking = client.post(
        f"{API}/auth/login", json={"email": ADMIN["email"], "password": "WrongPass1"}
    )
    assert locking.status_code == 423
    assert locking.json()["error"]["code"] == "account_locked"

    # Even the correct password is refused while the lock holds.
    correct = client.post(
        f"{API}/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
    )
    assert correct.status_code == 423

    locked_events = db.scalars(
        select(AuditLog).where(AuditLog.action == AuditAction.ACCOUNT_LOCKED.value)
    ).all()
    assert len(locked_events) == 1


def test_me_requires_a_token(client):
    assert client.get(f"{API}/auth/me").status_code == 401


def test_me_rejects_a_garbage_token(client):
    response = client.get(f"{API}/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_me_returns_the_signed_in_user(client, admin_headers):
    response = client.get(f"{API}/auth/me", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["email"] == ADMIN["email"]


def test_refresh_token_cannot_be_used_as_an_access_token(client, admin_user):
    tokens = client.post(
        f"{API}/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
    ).json()
    response = client.get(
        f"{API}/auth/me",
        headers={"Authorization": f"Bearer {tokens['refresh_token']}"},
    )
    assert response.status_code == 401


def test_refresh_issues_a_new_access_token(client, admin_user):
    tokens = client.post(
        f"{API}/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
    ).json()
    response = client.post(
        f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert response.status_code == 200
    assert decode_token(response.json()["access_token"], "access")["sub"] == tokens["user"]["id"]


def test_logout_revokes_the_refresh_token(client, admin_user):
    tokens = client.post(
        f"{API}/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    assert (
        client.post(
            f"{API}/auth/logout",
            json={"refresh_token": tokens["refresh_token"]},
            headers=headers,
        ).status_code
        == 200
    )

    reuse = client.post(
        f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reuse.status_code == 401


def test_expired_access_token_is_rejected(client, admin_user, monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_TOKEN_EXPIRE_MINUTES", -1)
    tokens = client.post(
        f"{API}/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
    ).json()

    with __import__("pytest").raises(jwt.ExpiredSignatureError):
        decode_token(tokens["access_token"], "access")

    response = client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert response.status_code == 401
    assert "expired" in response.json()["error"]["message"].lower()


def test_deactivated_user_is_denied(client, admin_headers, hr_user, db, admin_user):
    response = client.patch(
        f"{API}/users/{hr_user.id}", json={"is_active": False}, headers=admin_headers
    )
    assert response.status_code == 200

    login = client.post(
        f"{API}/auth/login", json={"email": HR["email"], "password": HR["password"]}
    )
    assert login.status_code == 401


def test_forgot_password_does_not_leak_account_existence(client, admin_user):
    known = client.post(f"{API}/auth/forgot-password", json={"email": ADMIN["email"]})
    unknown = client.post(
        f"{API}/auth/forgot-password", json={"email": "ghost@example.com"}
    )
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()


def test_password_reset_end_to_end(client, admin_user, db):
    from app.core.security import generate_url_token, hash_url_token, utcnow
    from datetime import timedelta
    from app.models.user import PasswordResetToken

    raw = generate_url_token()
    db.add(
        PasswordResetToken(
            user_id=admin_user.id,
            token_hash=hash_url_token(raw),
            expires_at=utcnow() + timedelta(minutes=30),
        )
    )
    db.commit()

    reset = client.post(
        f"{API}/auth/reset-password", json={"token": raw, "new_password": "BrandNew@99"}
    )
    assert reset.status_code == 200

    assert (
        client.post(
            f"{API}/auth/login",
            json={"email": ADMIN["email"], "password": ADMIN["password"]},
        ).status_code
        == 401
    )
    assert (
        client.post(
            f"{API}/auth/login",
            json={"email": ADMIN["email"], "password": "BrandNew@99"},
        ).status_code
        == 200
    )

    # A reset token is single-use.
    replay = client.post(
        f"{API}/auth/reset-password", json={"token": raw, "new_password": "Another@99"}
    )
    assert replay.status_code == 401


def test_weak_password_is_rejected_with_field_details(client, admin_user, db):
    from app.core.security import generate_url_token, hash_url_token, utcnow
    from datetime import timedelta
    from app.models.user import PasswordResetToken

    raw = generate_url_token()
    db.add(
        PasswordResetToken(
            user_id=admin_user.id,
            token_hash=hash_url_token(raw),
            expires_at=utcnow() + timedelta(minutes=30),
        )
    )
    db.commit()

    response = client.post(
        f"{API}/auth/reset-password", json={"token": raw, "new_password": "short"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]
