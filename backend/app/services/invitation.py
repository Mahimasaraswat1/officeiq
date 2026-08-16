"""Invitation issuance and employee-code generation."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_url_token, hash_url_token, utcnow
from app.models.employee import Employee, Invitation
from app.models.enums import InvitationStatus
from app.models.user import User

EMPLOYEE_CODE_PREFIX = "EMP"


def generate_employee_code(db: Session) -> str:
    """Sequential code such as EMP0007, based on the current row count."""
    count = db.scalar(select(func.count()).select_from(Employee)) or 0
    while True:
        candidate = f"{EMPLOYEE_CODE_PREFIX}{count + 1:04d}"
        exists = db.scalar(
            select(Employee.id).where(Employee.employee_code == candidate)
        )
        if exists is None:
            return candidate
        count += 1


def expire_stale_invitations(db: Session, employee_id) -> None:
    """Mark any pending-but-past-due invitations for an employee as expired."""
    now = utcnow()
    pending = db.scalars(
        select(Invitation).where(
            Invitation.employee_id == employee_id,
            Invitation.status == InvitationStatus.PENDING,
        )
    ).all()
    for invite in pending:
        if invite.expires_at <= now:
            invite.status = InvitationStatus.EXPIRED


def create_invitation(
    db: Session, *, employee: Employee, sent_by: User | None
) -> tuple[Invitation, str, datetime]:
    """Revoke any outstanding invite and issue a fresh one.

    Returns (invitation, raw_token, expires_at). The raw token is returned only
    so it can be emailed — it is never persisted.
    """
    now = utcnow()
    outstanding = db.scalars(
        select(Invitation).where(
            Invitation.employee_id == employee.id,
            Invitation.status == InvitationStatus.PENDING,
        )
    ).all()
    for invite in outstanding:
        invite.status = InvitationStatus.REVOKED
        invite.revoked_at = now

    raw_token = generate_url_token()
    expires_at = now + timedelta(hours=settings.INVITE_TOKEN_EXPIRE_HOURS)
    invitation = Invitation(
        employee_id=employee.id,
        email=employee.work_email,
        token_hash=hash_url_token(raw_token),
        status=InvitationStatus.PENDING,
        expires_at=expires_at,
        sent_by_id=sent_by.id if sent_by else None,
    )
    db.add(invitation)
    return invitation, raw_token, expires_at
