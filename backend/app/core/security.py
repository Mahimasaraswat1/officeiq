"""Password hashing, JWT issuance/verification, and one-time token helpers."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh"]

# bcrypt silently truncates anything past 72 bytes; reject instead of truncating.
MAX_PASSWORD_BYTES = 72


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Passwords -------------------------------------------------------------


def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    if len(pwd_bytes) > MAX_PASSWORD_BYTES:
        raise ValueError("Password must be at most 72 bytes long")
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash in the DB — treat as a failed login, never a 500.
        return False


# --- JWT -------------------------------------------------------------------


def _create_token(
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Return (encoded_jwt, jti, expires_at)."""
    now = utcnow()
    expires_at = now + expires_delta
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    encoded = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded, jti, expires_at


def create_access_token(subject: str, role: str) -> tuple[str, datetime]:
    token, _, expires_at = _create_token(
        subject,
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        {"role": role},
    )
    return token, expires_at


def create_refresh_token(subject: str) -> tuple[str, str, datetime]:
    """Return (token, jti, expires_at) — the jti is persisted so it can be revoked."""
    return _create_token(
        subject, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a JWT. Raises jwt.PyJWTError on any problem."""
    payload = jwt.decode(
        token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(
            f"Expected a {expected_type} token, got {payload.get('type')!r}"
        )
    return payload


# --- One-time tokens (invitations, password resets) ------------------------


def generate_url_token() -> str:
    """A high-entropy token safe to embed in an email link."""
    return secrets.token_urlsafe(48)


def hash_url_token(token: str) -> str:
    """Only the hash is stored, so a DB leak cannot be replayed as a valid link."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(token: str, stored_hash: str) -> bool:
    return secrets.compare_digest(hash_url_token(token), stored_hash)
