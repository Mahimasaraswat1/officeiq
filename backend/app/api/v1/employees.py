"""Employee profile CRUD + invitation management (PRD A.7.2 / B.4.2)."""

from __future__ import annotations

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import func, or_, select

from app.core.deps import CurrentUser, DbSession, HrUser
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.core.security import utcnow
from app.models.employee import Employee, Invitation
from app.models.enums import AuditAction, InvitationStatus, OnboardingStatus, UserRole
from app.models.user import User
from app.schemas.common import Message, Page
from app.schemas.employee import (
    EmployeeCreate,
    EmployeeRead,
    EmployeeSelfUpdate,
    EmployeeSummary,
    EmployeeUpdate,
    InvitationRead,
)
from app.services.audit import record_audit
from app.services.email import send_invitation_email
from app.services.invitation import (
    create_invitation,
    expire_stale_invitations,
    generate_employee_code,
)

router = APIRouter(prefix="/employees", tags=["Employees"])


def _get_employee_or_404(db: DbSession, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Employee not found.")
    return employee


def _assert_can_view(employee: Employee, user: User) -> None:
    """Employees may only read their own record; HR/Admin may read any."""
    if user.role in (UserRole.ADMIN, UserRole.HR):
        return
    if employee.user_id != user.id:
        raise PermissionDeniedError("You can only access your own employee record.")


# --- Self-service (must be declared before /{employee_id}) -----------------


@router.get("/me", response_model=EmployeeRead, summary="My own employee record")
def read_my_employee_record(db: DbSession, user: CurrentUser) -> EmployeeRead:
    employee = db.scalar(select(Employee).where(Employee.user_id == user.id))
    if employee is None:
        raise NotFoundError("No employee record is linked to this account.")
    return EmployeeRead.model_validate(employee)


@router.patch("/me", response_model=EmployeeRead, summary="Update my own details")
def update_my_employee_record(
    payload: EmployeeSelfUpdate, request: Request, db: DbSession, user: CurrentUser
) -> EmployeeRead:
    employee = db.scalar(select(Employee).where(Employee.user_id == user.id))
    if employee is None:
        raise NotFoundError("No employee record is linked to this account.")

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(employee, field, value)

    record_audit(
        db,
        action=AuditAction.PROFILE_UPDATED,
        actor=user,
        entity_type="employee",
        entity_id=employee.id,
        detail={"fields": sorted(changes.keys())},
        request=request,
    )
    db.commit()
    db.refresh(employee)
    return EmployeeRead.model_validate(employee)


# --- HR/Admin CRUD ---------------------------------------------------------


@router.get("", response_model=Page[EmployeeSummary], summary="List / search employees")
def list_employees(
    db: DbSession,
    _: HrUser,
    search: Annotated[
        str | None, Query(description="Match on name, employee code, or work email")
    ] = None,
    department: str | None = None,
    onboarding_status: OnboardingStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[EmployeeSummary]:
    filters = []
    if search:
        term = f"%{search.strip().lower()}%"
        filters.append(
            or_(
                func.lower(Employee.first_name).like(term),
                func.lower(Employee.last_name).like(term),
                func.lower(Employee.employee_code).like(term),
                func.lower(Employee.work_email).like(term),
            )
        )
    if department:
        filters.append(func.lower(Employee.department) == department.strip().lower())
    if onboarding_status:
        filters.append(Employee.onboarding_status == onboarding_status)

    total = db.scalar(select(func.count()).select_from(Employee).where(*filters)) or 0
    rows = db.scalars(
        select(Employee)
        .where(*filters)
        .order_by(Employee.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return Page[EmployeeSummary](
        items=[EmployeeSummary.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.post(
    "",
    response_model=EmployeeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an employee profile and send the onboarding invite",
)
def create_employee(
    payload: EmployeeCreate, request: Request, db: DbSession, actor: HrUser
) -> EmployeeRead:
    work_email = payload.work_email.strip().lower()

    if db.scalar(select(Employee.id).where(Employee.work_email == work_email)):
        raise ConflictError("An employee with that work email already exists.")
    if db.scalar(select(User.id).where(User.email == work_email)):
        raise ConflictError("A user account with that email already exists.")

    code = (payload.employee_code or "").strip().upper() or generate_employee_code(db)
    if db.scalar(select(Employee.id).where(Employee.employee_code == code)):
        raise ConflictError(f"Employee code {code} is already in use.")

    data = payload.model_dump(exclude={"employee_code", "send_invite", "work_email"})
    employee = Employee(
        **data,
        work_email=work_email,
        employee_code=code,
        onboarding_status=OnboardingStatus.INVITED,
        created_by_id=actor.id,
    )
    db.add(employee)
    db.flush()  # assign employee.id before creating the invitation

    record_audit(
        db,
        action=AuditAction.EMPLOYEE_CREATED,
        actor=actor,
        entity_type="employee",
        entity_id=employee.id,
        detail={"employee_code": code, "work_email": work_email},
        request=request,
    )

    raw_token = expires_at = None
    if payload.send_invite:
        _, raw_token, expires_at = create_invitation(db, employee=employee, sent_by=actor)
        record_audit(
            db,
            action=AuditAction.INVITATION_SENT,
            actor=actor,
            entity_type="employee",
            entity_id=employee.id,
            detail={"email": work_email},
            request=request,
        )

    db.commit()
    db.refresh(employee)

    if raw_token:
        send_invitation_email(
            to=employee.work_email,
            employee_name=employee.full_name,
            token=raw_token,
            expires_at=expires_at,
        )

    return EmployeeRead.model_validate(employee)


@router.get("/{employee_id}", response_model=EmployeeRead, summary="Get one employee")
def get_employee(
    employee_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> EmployeeRead:
    employee = _get_employee_or_404(db, employee_id)
    _assert_can_view(employee, user)
    return EmployeeRead.model_validate(employee)


@router.patch("/{employee_id}", response_model=EmployeeRead, summary="Update an employee")
def update_employee(
    employee_id: uuid.UUID,
    payload: EmployeeUpdate,
    request: Request,
    db: DbSession,
    actor: HrUser,
) -> EmployeeRead:
    employee = _get_employee_or_404(db, employee_id)
    changes = payload.model_dump(exclude_unset=True)

    new_status = changes.get("onboarding_status")
    if new_status == OnboardingStatus.COMPLETE and employee.onboarding_completed_at is None:
        employee.onboarding_completed_at = utcnow()
    elif new_status is not None and new_status != OnboardingStatus.COMPLETE:
        employee.onboarding_completed_at = None

    for field, value in changes.items():
        setattr(employee, field, value)

    record_audit(
        db,
        action=AuditAction.EMPLOYEE_UPDATED,
        actor=actor,
        entity_type="employee",
        entity_id=employee.id,
        detail={"fields": sorted(changes.keys())},
        request=request,
    )
    db.commit()
    db.refresh(employee)
    return EmployeeRead.model_validate(employee)


@router.delete(
    "/{employee_id}",
    response_model=Message,
    summary="Delete an employee profile (Admin only)",
)
def delete_employee(
    employee_id: uuid.UUID, request: Request, db: DbSession, actor: CurrentUser
) -> Message:
    if actor.role is not UserRole.ADMIN:
        raise PermissionDeniedError("Only an administrator can delete employee records.")

    employee = _get_employee_or_404(db, employee_id)
    record_audit(
        db,
        action=AuditAction.EMPLOYEE_DELETED,
        actor=actor,
        entity_type="employee",
        entity_id=employee.id,
        detail={"employee_code": employee.employee_code, "work_email": employee.work_email},
        request=request,
    )
    db.delete(employee)
    db.commit()
    return Message(message="Employee profile deleted.")


# --- Invitations -----------------------------------------------------------


@router.get(
    "/{employee_id}/invitations",
    response_model=list[InvitationRead],
    summary="Invitation history for an employee",
)
def list_invitations(
    employee_id: uuid.UUID, db: DbSession, _: HrUser
) -> list[InvitationRead]:
    employee = _get_employee_or_404(db, employee_id)
    expire_stale_invitations(db, employee.id)
    db.commit()
    rows = db.scalars(
        select(Invitation)
        .where(Invitation.employee_id == employee.id)
        .order_by(Invitation.created_at.desc())
    ).all()
    return [InvitationRead.model_validate(row) for row in rows]


@router.post(
    "/{employee_id}/invite",
    response_model=InvitationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Send or resend the onboarding invitation",
)
def resend_invitation(
    employee_id: uuid.UUID, request: Request, db: DbSession, actor: HrUser
) -> InvitationRead:
    employee = _get_employee_or_404(db, employee_id)
    if employee.user_id is not None:
        raise ConflictError("This employee has already completed registration.")

    invitation, raw_token, expires_at = create_invitation(
        db, employee=employee, sent_by=actor
    )
    record_audit(
        db,
        action=AuditAction.INVITATION_RESENT,
        actor=actor,
        entity_type="employee",
        entity_id=employee.id,
        detail={"email": employee.work_email},
        request=request,
    )
    db.commit()
    db.refresh(invitation)

    send_invitation_email(
        to=employee.work_email,
        employee_name=employee.full_name,
        token=raw_token,
        expires_at=expires_at,
    )
    return InvitationRead.model_validate(invitation)


@router.post(
    "/{employee_id}/invite/revoke",
    response_model=Message,
    summary="Revoke any outstanding invitation",
)
def revoke_invitation(
    employee_id: uuid.UUID, request: Request, db: DbSession, actor: HrUser
) -> Message:
    employee = _get_employee_or_404(db, employee_id)
    now = utcnow()
    pending = db.scalars(
        select(Invitation).where(
            Invitation.employee_id == employee.id,
            Invitation.status == InvitationStatus.PENDING,
        )
    ).all()
    if not pending:
        raise NotFoundError("There is no outstanding invitation to revoke.")

    for invite in pending:
        invite.status = InvitationStatus.REVOKED
        invite.revoked_at = now

    record_audit(
        db,
        action=AuditAction.INVITATION_REVOKED,
        actor=actor,
        entity_type="employee",
        entity_id=employee.id,
        detail={"revoked": len(pending)},
        request=request,
    )
    db.commit()
    return Message(message=f"Revoked {len(pending)} outstanding invitation(s).")
