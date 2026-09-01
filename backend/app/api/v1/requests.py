"""Employee requests and the approval queue.

Two audiences share one resource: an employee sees only their own requests,
HR/Admin see the queue. Every route resolves what the caller may do from the
row itself rather than from the path, so there is no "read someone else's
request" URL for any role.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request as HttpRequest, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, HrUser
from app.core.errors import NotFoundError, PermissionDeniedError
from app.models.employee import Employee
from app.models.enums import AuditAction, RequestStatus, RequestType, UserRole
from app.models.request import Request
from app.schemas.request import (
    LeaveBalanceRead,
    LeaveBalanceSummary,
    RequestCounts,
    RequestCreate,
    RequestDecision,
    RequestRead,
    RequestRejection,
)
from app.core.security import today_utc
from app.services.audit import record_audit
from app.services.leave import balances_for
from app.services.requests import (
    approve,
    can_cancel,
    can_decide,
    cancel,
    for_employee,
    owns,
    queue,
    reject,
    submit,
)

router = APIRouter(tags=["Requests & Approvals"])


def _my_employee(db: DbSession, user) -> Employee:
    employee = db.scalar(select(Employee).where(Employee.user_id == user.id))
    if employee is None:
        raise NotFoundError("No employee record is linked to this account.")
    return employee


def _to_read(request: Request, *, viewer) -> RequestRead:
    employee = request.employee
    return RequestRead(
        id=request.id,
        request_code=request.request_code,
        type=request.type,
        status=request.status,
        payload=request.payload,
        summary=request.summary,
        employee_id=employee.id,
        employee_name=f"{employee.first_name} {employee.last_name}",
        employee_code=employee.employee_code,
        submitted_at=request.submitted_at,
        decided_at=request.decided_at,
        decided_by_name=request.decided_by.full_name if request.decided_by else None,
        decision_note=request.decision_note,
        can_decide=request.is_open and can_decide(viewer, request),
        can_cancel=can_cancel(viewer, request),
    )


def _get_visible(db: DbSession, request_id: uuid.UUID, viewer) -> Request:
    """Fetch a request the viewer is allowed to see.

    A missing row and someone else's row return the same 404, so an id belonging
    to another employee is not confirmed to exist.
    """
    request = db.get(Request, request_id)
    if request is None:
        raise NotFoundError("Request not found.")
    if viewer.role not in (UserRole.HR, UserRole.ADMIN) and not owns(viewer, request):
        raise NotFoundError("Request not found.")
    return request


# --- Employee-facing ---------------------------------------------------------


@router.get("/my-requests", response_model=list[RequestRead], summary="My requests")
def list_my_requests(db: DbSession, user: CurrentUser) -> list[RequestRead]:
    employee = _my_employee(db, user)
    return [_to_read(r, viewer=user) for r in for_employee(db, employee_id=employee.id)]


@router.post(
    "/my-requests",
    response_model=RequestRead,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a request",
)
def create_request(
    db: DbSession, user: CurrentUser, payload: RequestCreate, http_request: HttpRequest
) -> RequestRead:
    employee = _my_employee(db, user)
    request = submit(
        db,
        employee=employee,
        request_type=payload.type,
        raw_payload=payload.payload,
        actor=user,
    )
    record_audit(
        db,
        action=AuditAction.REQUEST_SUBMITTED,
        actor=user,
        entity_type="request",
        entity_id=request.id,
        detail={"code": request.request_code, "type": request.type.value},
        request=http_request,
    )
    db.commit()
    db.refresh(request)
    return _to_read(request, viewer=user)


@router.post(
    "/my-requests/{request_id}/cancel",
    response_model=RequestRead,
    summary="Withdraw my request",
)
def cancel_request(
    db: DbSession, user: CurrentUser, request_id: uuid.UUID, http_request: HttpRequest
) -> RequestRead:
    request = _get_visible(db, request_id, user)
    cancel(db, request=request, actor=user)
    record_audit(
        db,
        action=AuditAction.REQUEST_CANCELLED,
        actor=user,
        entity_type="request",
        entity_id=request.id,
        detail={"code": request.request_code},
        request=http_request,
    )
    db.commit()
    db.refresh(request)
    return _to_read(request, viewer=user)


@router.get(
    "/my-leave-balance",
    response_model=LeaveBalanceSummary,
    summary="My leave balance",
)
def my_leave_balance(
    db: DbSession,
    user: CurrentUser,
    year: Annotated[int | None, Query(ge=1970, le=2200)] = None,
) -> LeaveBalanceSummary:
    """This year's entitlement, usage and remainder.

    Rows are created on first read rather than by a year-start job, so a new
    employee sees a correct pro-rated balance without anything having run.
    """
    employee = _my_employee(db, user)
    resolved = year if year is not None else today_utc().year
    rows = balances_for(db, employee=employee, year=resolved)
    db.commit()

    return LeaveBalanceSummary(
        year=resolved,
        balances=[
            LeaveBalanceRead(
                leave_kind=b.leave_kind,
                year=b.year,
                entitled_days=float(b.entitled_days),
                carried_forward_days=float(b.carried_forward_days),
                used_days=float(b.used_days),
                available_days=float(b.available_days),
            )
            for b in rows
        ],
    )


# --- Approver-facing ---------------------------------------------------------


@router.get("/requests", response_model=list[RequestRead], summary="Approval queue")
def list_queue(
    db: DbSession,
    user: HrUser,
    status_filter: Annotated[RequestStatus | None, Query(alias="status")] = None,
    type_filter: Annotated[RequestType | None, Query(alias="type")] = None,
) -> list[RequestRead]:
    rows = queue(db, status=status_filter, request_type=type_filter)
    return [_to_read(r, viewer=user) for r in rows]


@router.get("/requests/counts", response_model=RequestCounts, summary="Queue counts")
def counts(db: DbSession, _: HrUser) -> RequestCounts:
    rows = dict(
        db.execute(select(Request.status, func.count()).group_by(Request.status)).all()
    )
    return RequestCounts(
        pending=rows.get(RequestStatus.PENDING, 0),
        approved=rows.get(RequestStatus.APPROVED, 0),
        rejected=rows.get(RequestStatus.REJECTED, 0),
        cancelled=rows.get(RequestStatus.CANCELLED, 0),
    )


@router.get("/requests/{request_id}", response_model=RequestRead, summary="One request")
def read_request(db: DbSession, user: CurrentUser, request_id: uuid.UUID) -> RequestRead:
    return _to_read(_get_visible(db, request_id, user), viewer=user)


@router.post(
    "/requests/{request_id}/approve", response_model=RequestRead, summary="Approve"
)
def approve_request(
    db: DbSession,
    user: HrUser,
    request_id: uuid.UUID,
    payload: RequestDecision,
    http_request: HttpRequest,
) -> RequestRead:
    request = _get_visible(db, request_id, user)
    approve(db, request=request, actor=user, note=payload.note)
    record_audit(
        db,
        action=AuditAction.REQUEST_APPROVED,
        actor=user,
        entity_type="request",
        entity_id=request.id,
        detail={"code": request.request_code},
        request=http_request,
    )
    db.commit()
    db.refresh(request)
    return _to_read(request, viewer=user)


@router.post(
    "/requests/{request_id}/reject", response_model=RequestRead, summary="Reject"
)
def reject_request(
    db: DbSession,
    user: HrUser,
    request_id: uuid.UUID,
    payload: RequestRejection,
    http_request: HttpRequest,
) -> RequestRead:
    request = _get_visible(db, request_id, user)
    reject(db, request=request, actor=user, note=payload.note)
    record_audit(
        db,
        action=AuditAction.REQUEST_REJECTED,
        actor=user,
        entity_type="request",
        entity_id=request.id,
        detail={"code": request.request_code},
        request=http_request,
    )
    db.commit()
    db.refresh(request)
    return _to_read(request, viewer=user)
