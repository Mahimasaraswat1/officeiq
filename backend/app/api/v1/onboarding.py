"""Public, token-gated employee self-registration (PRD A.6 steps 2-3)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.core.deps import DbSession
from app.core.errors import AuthenticationError, ConflictError
from app.core.security import hash_password, hash_url_token, utcnow
from app.models.employee import Employee, Invitation
from app.models.enums import AuditAction, InvitationStatus, OnboardingStatus, UserRole
from app.models.user import User
from app.schemas.employee import (
    AcceptInvitationRequest,
    AcceptInvitationResponse,
    EmployeeRead,
    InvitationPreview,
)
from app.schemas.user import UserRead
from app.services.audit import record_audit
from app.services.notifications import notify_invitation_accepted

router = APIRouter(prefix="/onboarding", tags=["Onboarding (public)"])

_INVALID_TOKEN = "This invitation link is invalid, expired, or already used."


def _resolve_invitation(db: DbSession, token: str) -> tuple[Invitation, Employee]:
    invitation = db.scalar(
        select(Invitation).where(Invitation.token_hash == hash_url_token(token))
    )
    if invitation is None or invitation.status is not InvitationStatus.PENDING:
        raise AuthenticationError(_INVALID_TOKEN)

    if invitation.expires_at <= utcnow():
        invitation.status = InvitationStatus.EXPIRED
        db.commit()
        raise AuthenticationError(_INVALID_TOKEN)

    employee = db.get(Employee, invitation.employee_id)
    if employee is None:
        raise AuthenticationError(_INVALID_TOKEN)
    return invitation, employee


@router.get(
    "/invitation",
    response_model=InvitationPreview,
    summary="Validate an invite token and pre-fill the signup form",
)
def preview_invitation(db: DbSession, token: str = Query(min_length=16)) -> InvitationPreview:
    invitation, employee = _resolve_invitation(db, token)
    return InvitationPreview(
        email=employee.work_email,
        first_name=employee.first_name,
        last_name=employee.last_name,
        employee_code=employee.employee_code,
        department=employee.department,
        designation=employee.designation,
        expires_at=invitation.expires_at,
    )


@router.post(
    "/accept",
    response_model=AcceptInvitationResponse,
    summary="Accept an invitation, set a password, and activate the account",
)
def accept_invitation(
    payload: AcceptInvitationRequest, request: Request, db: DbSession
) -> AcceptInvitationResponse:
    invitation, employee = _resolve_invitation(db, payload.token)

    if employee.user_id is not None:
        raise ConflictError("An account has already been created for this invitation.")
    if db.scalar(select(User.id).where(User.email == employee.work_email)):
        raise ConflictError("A user account with that email already exists.")

    now = utcnow()
    user = User(
        email=employee.work_email,
        hashed_password=hash_password(payload.password),
        full_name=employee.full_name,
        role=UserRole.EMPLOYEE,
        is_active=True,
    )
    db.add(user)
    db.flush()

    employee.user_id = user.id
    employee.onboarding_status = OnboardingStatus.REGISTERED
    if payload.phone:
        employee.phone = payload.phone

    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_at = now

    record_audit(
        db,
        action=AuditAction.INVITATION_ACCEPTED,
        actor=user,
        entity_type="employee",
        entity_id=employee.id,
        detail={"employee_code": employee.employee_code},
        request=request,
    )
    record_audit(
        db,
        action=AuditAction.USER_CREATED,
        actor=user,
        entity_type="user",
        entity_id=user.id,
        detail={"role": UserRole.EMPLOYEE.value, "source": "invitation"},
        request=request,
    )
    notify_invitation_accepted(db, employee=employee)
    db.commit()
    db.refresh(user)
    db.refresh(employee)

    return AcceptInvitationResponse(
        message="Your account is ready. You can now sign in.",
        user=UserRead.model_validate(user),
        employee=EmployeeRead.model_validate(employee),
    )
