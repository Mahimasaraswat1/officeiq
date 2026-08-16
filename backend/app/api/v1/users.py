"""Admin user/role management + self-service profile (PRD A.5 / A.7.10)."""

from __future__ import annotations

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import func, or_, select

from app.core.config import settings
from app.core.deps import AdminUser, CurrentUser, DbSession
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.security import hash_password, utcnow, verify_password
from app.models.audit import AuditLog
from app.models.enums import AuditAction, UserRole
from app.models.user import RefreshToken, User
from app.schemas.common import Message, Page
from app.schemas.user import (
    ActivityEntry,
    PasswordChange,
    ProfileUpdate,
    SessionRead,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.services.audit import record_audit

router = APIRouter(tags=["Users & Profile"])


# --- Self-service ----------------------------------------------------------


@router.get("/profile", response_model=UserRead, summary="My account")
def get_profile(user: CurrentUser) -> UserRead:
    return UserRead.model_validate(user)


@router.patch("/profile", response_model=UserRead, summary="Update my account")
def update_profile(
    payload: ProfileUpdate, request: Request, db: DbSession, user: CurrentUser
) -> UserRead:
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    record_audit(
        db,
        action=AuditAction.PROFILE_UPDATED,
        actor=user,
        entity_type="user",
        entity_id=user.id,
        detail={"fields": sorted(changes.keys())},
        request=request,
    )
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.post("/profile/password", response_model=Message, summary="Change my password")
def change_password(
    payload: PasswordChange, request: Request, db: DbSession, user: CurrentUser
) -> Message:
    if not verify_password(payload.current_password, user.hashed_password):
        raise PermissionDeniedError("Your current password is incorrect.")
    if payload.current_password == payload.new_password:
        raise ConflictError("The new password must differ from the current one.")

    user.hashed_password = hash_password(payload.new_password)
    now = utcnow()
    for token in user.refresh_tokens:
        if token.revoked_at is None:
            token.revoked_at = now

    record_audit(
        db,
        action=AuditAction.PASSWORD_CHANGED,
        actor=user,
        entity_type="user",
        entity_id=user.id,
        request=request,
    )
    db.commit()
    return Message(message="Password updated. Please sign in again on other devices.")


# --- Sessions & personal activity (Phase 7) --------------------------------


@router.get(
    "/profile/sessions",
    response_model=list[SessionRead],
    summary="Devices currently signed in as me",
)
def list_sessions(db: DbSession, user: CurrentUser) -> list[SessionRead]:
    """Active refresh tokens, most recently used first.

    Expired and revoked sessions are left out rather than greyed out — the
    question this answers is "who can get in right now?".
    """
    now = utcnow()
    sessions = db.scalars(
        select(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .order_by(
            RefreshToken.last_used_at.desc().nullslast(), RefreshToken.created_at.desc()
        )
    ).all()
    return [SessionRead.model_validate(session) for session in sessions]


@router.delete(
    "/profile/sessions/{session_id}",
    response_model=Message,
    summary="Sign one device out",
)
def revoke_session(
    session_id: uuid.UUID, request: Request, db: DbSession, user: CurrentUser
) -> Message:
    # Matched on owner as well as id, so a wrong guess cannot confirm that
    # somebody else's session exists.
    session = db.scalar(
        select(RefreshToken).where(
            RefreshToken.id == session_id, RefreshToken.user_id == user.id
        )
    )
    if session is None:
        raise NotFoundError("Session not found.")

    if session.revoked_at is None:
        session.revoked_at = utcnow()
        record_audit(
            db,
            action=AuditAction.SESSION_REVOKED,
            actor=user,
            entity_type="session",
            entity_id=session.id,
            detail={"scope": "single"},
            request=request,
        )
        db.commit()
    return Message(message="That device has been signed out.")


@router.post(
    "/profile/sessions/revoke-all",
    response_model=Message,
    summary="Sign out of every device",
)
def revoke_all_sessions(request: Request, db: DbSession, user: CurrentUser) -> Message:
    now = utcnow()
    revoked = 0
    for token in user.refresh_tokens:
        if token.revoked_at is None and token.expires_at > now:
            token.revoked_at = now
            revoked += 1

    if revoked:
        record_audit(
            db,
            action=AuditAction.SESSION_REVOKED,
            actor=user,
            entity_type="user",
            entity_id=user.id,
            detail={"scope": "all", "count": revoked},
            request=request,
        )
    db.commit()
    # Access tokens are stateless, so revoking refresh tokens ends sessions at
    # the next refresh rather than instantly. Say so instead of implying more.
    return Message(
        message=(
            f"Signed out of {revoked} device(s). Any access token already issued "
            f"stops working within {settings.ACCESS_TOKEN_EXPIRE_MINUTES} minutes."
        )
    )


@router.get(
    "/profile/activity",
    response_model=list[ActivityEntry],
    summary="My own recent account activity",
)
def my_activity(
    db: DbSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=50)] = 15,
) -> list[ActivityEntry]:
    """Scoped to entries where this user is the actor — never anyone else's."""
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.actor_user_id == user.id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).all()
    return [
        ActivityEntry(
            id=row.id,
            action=row.action,
            entity_type=row.entity_type,
            ip_address=row.ip_address,
            created_at=row.created_at,
        )
        for row in rows
    ]


# --- Admin -----------------------------------------------------------------


@router.get("/users", response_model=Page[UserRead], summary="List users (Admin)")
def list_users(
    db: DbSession,
    _: AdminUser,
    search: str | None = None,
    role: UserRole | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[UserRead]:
    filters = []
    if search:
        term = f"%{search.strip().lower()}%"
        filters.append(
            or_(func.lower(User.email).like(term), func.lower(User.full_name).like(term))
        )
    if role:
        filters.append(User.role == role)

    total = db.scalar(select(func.count()).select_from(User).where(*filters)) or 0
    rows = db.scalars(
        select(User)
        .where(*filters)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return Page[UserRead](
        items=[UserRead.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.post(
    "/users",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an Admin/HR account (Admin)",
)
def create_user(
    payload: UserCreate, request: Request, db: DbSession, actor: AdminUser
) -> UserRead:
    email = payload.email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise ConflictError("A user with that email already exists.")
    if payload.role is UserRole.EMPLOYEE:
        raise ConflictError(
            "Employee accounts are created through the onboarding invitation flow."
        )

    user = User(
        email=email,
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        role=payload.role,
    )
    db.add(user)
    db.flush()

    record_audit(
        db,
        action=AuditAction.USER_CREATED,
        actor=actor,
        entity_type="user",
        entity_id=user.id,
        detail={"email": email, "role": payload.role.value},
        request=request,
    )
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserRead, summary="Update a user (Admin)")
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    request: Request,
    db: DbSession,
    actor: AdminUser,
) -> UserRead:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")

    changes = payload.model_dump(exclude_unset=True)

    # Guard against an admin locking themselves out of their own account.
    if user.id == actor.id:
        if changes.get("is_active") is False:
            raise ConflictError("You cannot deactivate your own account.")
        if "role" in changes and changes["role"] is not UserRole.ADMIN:
            raise ConflictError("You cannot change your own role away from Admin.")

    for field, value in changes.items():
        setattr(user, field, value)

    if changes.get("is_active") is True:
        user.failed_login_attempts = 0
        user.locked_until = None

    record_audit(
        db,
        action=AuditAction.USER_UPDATED,
        actor=actor,
        entity_type="user",
        entity_id=user.id,
        detail={"fields": sorted(changes.keys())},
        request=request,
    )
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)
