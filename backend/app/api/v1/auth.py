"""Authentication: login, refresh, logout, password reset (PRD A.7.1 / B.4.1)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.errors import AccountLockedError, AuthenticationError
from app.core.ratelimit import login_rate_limit, password_reset_rate_limit
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_url_token,
    hash_password,
    hash_url_token,
    utcnow,
    verify_password,
)
from app.models.enums import AuditAction
from app.models.user import PasswordResetToken, RefreshToken, User
from app.schemas.common import Message
from app.schemas.user import (
    AccessTokenResponse,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
    TokenPair,
    UserRead,
)
from app.services.audit import client_ip, record_audit
from app.services.email import send_password_reset_email

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Deliberately vague so the endpoint cannot be used to enumerate accounts.
_INVALID_CREDENTIALS = "Incorrect email or password."


def _issue_token_pair(db: DbSession, user: User, request: Request | None = None) -> TokenPair:
    access_token, expires_at = create_access_token(str(user.id), user.role.value)
    refresh_token, jti, refresh_expires = create_refresh_token(str(user.id))
    db.add(
        RefreshToken(
            jti=jti,
            user_id=user.id,
            expires_at=refresh_expires,
            user_agent=(request.headers.get("user-agent", "")[:255] or None) if request else None,
            ip_address=client_ip(request),
            last_used_at=utcnow(),
        )
    )
    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        user=UserRead.model_validate(user),
    )


@router.post(
    "/login",
    response_model=TokenPair,
    summary="Sign in and receive a token pair",
    # Per-IP, on top of the per-account lockout: the lockout stops one account
    # being brute forced, this stops one source trying a thousand accounts.
    dependencies=[Depends(login_rate_limit)],
)
def login(payload: LoginRequest, request: Request, db: DbSession) -> TokenPair:
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    now = utcnow()

    if user is None:
        record_audit(
            db,
            action=AuditAction.LOGIN_FAILED,
            actor_email=email,
            detail={"reason": "unknown_email"},
            request=request,
        )
        db.commit()
        raise AuthenticationError(_INVALID_CREDENTIALS)

    if user.locked_until and user.locked_until > now:
        minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise AccountLockedError(
            f"Too many failed attempts. Try again in about {minutes} minute(s)."
        )

    if not verify_password(payload.password, user.hashed_password):
        user.failed_login_attempts += 1
        locked = user.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS
        if locked:
            user.locked_until = now + timedelta(minutes=settings.ACCOUNT_LOCKOUT_MINUTES)
            user.failed_login_attempts = 0
            record_audit(
                db,
                action=AuditAction.ACCOUNT_LOCKED,
                actor=user,
                entity_type="user",
                entity_id=user.id,
                detail={"locked_minutes": settings.ACCOUNT_LOCKOUT_MINUTES},
                request=request,
            )
        record_audit(
            db,
            action=AuditAction.LOGIN_FAILED,
            actor=user,
            detail={"reason": "bad_password", "attempts": user.failed_login_attempts},
            request=request,
        )
        db.commit()
        if locked:
            raise AccountLockedError(
                "Too many failed attempts. This account is locked for "
                f"{settings.ACCOUNT_LOCKOUT_MINUTES} minutes."
            )
        raise AuthenticationError(_INVALID_CREDENTIALS)

    if not user.is_active:
        record_audit(
            db,
            action=AuditAction.LOGIN_FAILED,
            actor=user,
            detail={"reason": "inactive"},
            request=request,
        )
        db.commit()
        raise AuthenticationError("This account has been deactivated. Contact your administrator.")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = now

    tokens = _issue_token_pair(db, user, request)
    record_audit(
        db,
        action=AuditAction.LOGIN_SUCCESS,
        actor=user,
        entity_type="user",
        entity_id=user.id,
        request=request,
    )
    db.commit()
    return tokens


@router.post("/refresh", response_model=AccessTokenResponse, summary="Exchange a refresh token")
def refresh(payload: RefreshRequest, request: Request, db: DbSession) -> AccessTokenResponse:
    try:
        claims = decode_token(payload.refresh_token, "refresh")
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Refresh token has expired. Please sign in again.") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationError("Invalid refresh token.") from exc

    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == claims["jti"]))
    if stored is None or stored.revoked_at is not None:
        raise AuthenticationError("This session has been revoked. Please sign in again.")

    user = db.get(User, uuid.UUID(str(claims["sub"])))
    if user is None or not user.is_active:
        raise AuthenticationError("Account is unavailable.")

    stored.last_used_at = utcnow()
    access_token, expires_at = create_access_token(str(user.id), user.role.value)
    record_audit(db, action=AuditAction.TOKEN_REFRESHED, actor=user, request=request)
    db.commit()
    return AccessTokenResponse(access_token=access_token, expires_at=expires_at)


@router.post("/logout", response_model=Message, summary="Revoke the current refresh token")
def logout(
    payload: RefreshRequest, request: Request, db: DbSession, user: CurrentUser
) -> Message:
    try:
        claims = decode_token(payload.refresh_token, "refresh")
    except jwt.PyJWTError:
        # An unusable token is already effectively logged out.
        return Message(message="Signed out.")

    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == claims["jti"]))
    if stored is not None and stored.user_id == user.id and stored.revoked_at is None:
        stored.revoked_at = utcnow()
    record_audit(db, action=AuditAction.LOGOUT, actor=user, request=request)
    db.commit()
    return Message(message="Signed out.")


@router.get("/me", response_model=UserRead, summary="Current signed-in user")
def me(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.post(
    "/forgot-password",
    response_model=Message,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password-reset link",
    # Unauthenticated and it sends email — without a limit this is a way to
    # spam somebody else's inbox from our domain.
    dependencies=[Depends(password_reset_rate_limit)],
)
def forgot_password(
    payload: ForgotPasswordRequest, request: Request, db: DbSession
) -> Message:
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))

    # Always return the same response so accounts cannot be enumerated.
    generic = Message(
        message="If an account exists for that address, a reset link has been sent."
    )
    if user is None or not user.is_active:
        return generic

    raw_token = generate_url_token()
    expires_at = utcnow() + timedelta(
        minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
    )
    db.add(
        PasswordResetToken(
            user_id=user.id, token_hash=hash_url_token(raw_token), expires_at=expires_at
        )
    )
    record_audit(
        db,
        action=AuditAction.PASSWORD_RESET_REQUESTED,
        actor=user,
        entity_type="user",
        entity_id=user.id,
        request=request,
    )
    db.commit()

    send_password_reset_email(
        to=user.email, name=user.full_name, token=raw_token, expires_at=expires_at
    )
    return generic


@router.post(
    "/reset-password",
    response_model=Message,
    summary="Set a new password via token",
    dependencies=[Depends(password_reset_rate_limit)],
)
def reset_password(
    payload: ResetPasswordRequest, request: Request, db: DbSession
) -> Message:
    record = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == hash_url_token(payload.token)
        )
    )
    now = utcnow()
    if record is None or record.used_at is not None or record.expires_at <= now:
        raise AuthenticationError("This reset link is invalid or has expired.")

    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("This reset link is invalid or has expired.")

    user.hashed_password = hash_password(payload.new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    record.used_at = now

    # Force every existing session to re-authenticate.
    for token in user.refresh_tokens:
        if token.revoked_at is None:
            token.revoked_at = now

    record_audit(
        db,
        action=AuditAction.PASSWORD_RESET_COMPLETED,
        actor=user,
        entity_type="user",
        entity_id=user.id,
        request=request,
    )
    db.commit()
    return Message(message="Your password has been reset. You can now sign in.")
