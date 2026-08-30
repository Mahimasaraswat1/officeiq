"""The request engine: payload validation, routing, and decisions.

Everything type-specific lives in the registry at the top of this file. The
functions below it — submit, approve, reject, cancel — never branch on the
request type, which is what keeps a new type from touching the engine.

To add a type:
  1. add a value to RequestType
  2. write a payload model and register it with @payload_for(RequestType.X)
  3. give it a summary line
Nothing else in this module changes.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date
from typing import ClassVar

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, PermissionDeniedError, ValidationError
from app.core.security import utcnow
from app.models.employee import Employee
from app.models.enums import NotificationType, RequestStatus, RequestType, UserRole
from app.models.request import Request
from app.models.user import User
from app.services.notifications import employee_recipient, notify, notify_hr

# --- Payload registry --------------------------------------------------------

PAYLOAD_MODELS: dict[RequestType, type[BaseModel]] = {}


def payload_for(request_type: RequestType) -> Callable[[type[BaseModel]], type[BaseModel]]:
    """Register the payload model that validates this request type."""

    def register(model: type[BaseModel]) -> type[BaseModel]:
        PAYLOAD_MODELS[request_type] = model
        return model

    return register


class RequestPayload(BaseModel):
    """Base for every type's payload.

    `summarise()` is what the approval queue and the notifications render, so
    each type states its own one-liner rather than every consumer learning to
    read every payload shape.
    """

    label: ClassVar[str] = "Request"

    def summarise(self) -> str:  # pragma: no cover - overridden by every type
        return self.label


LEAVE_KINDS = ("casual", "sick", "earned", "unpaid")


@payload_for(RequestType.LEAVE)
class LeavePayload(RequestPayload):
    """A leave request.

    Entitlement and balance are deliberately not checked here — that is the
    Leave Application module. This validates only what makes the request
    coherent on its own terms.
    """

    label: ClassVar[str] = "Leave"

    leave_kind: str = Field(description="One of: " + ", ".join(LEAVE_KINDS))
    start_date: date
    end_date: date
    half_day: bool = False
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _check(self) -> "LeavePayload":
        if self.leave_kind not in LEAVE_KINDS:
            raise ValueError(f"leave_kind must be one of: {', '.join(LEAVE_KINDS)}")
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date")
        if self.half_day and self.start_date != self.end_date:
            raise ValueError("a half day must start and end on the same date")
        if self.days > 365:
            raise ValueError("a single request cannot cover more than a year")
        return self

    @property
    def days(self) -> float:
        """Calendar days spanned. Working-day and holiday-aware counting belongs
        to the Leave module, which knows the holiday calendar; this is the
        honest span of the request itself."""
        if self.half_day:
            return 0.5
        return float((self.end_date - self.start_date).days + 1)

    def summarise(self) -> str:
        span = (
            self.start_date.strftime("%d %b")
            if self.start_date == self.end_date
            else f"{self.start_date.strftime('%d %b')} – {self.end_date.strftime('%d %b %Y')}"
        )
        unit = "half day" if self.half_day else f"{self.days:g} day{'s' if self.days != 1 else ''}"
        return f"{self.leave_kind.title()} leave · {unit} · {span}"


def validate_payload(request_type: RequestType, raw: dict) -> RequestPayload:
    """Parse a payload against its type's model, or explain why it does not fit."""
    model = PAYLOAD_MODELS.get(request_type)
    if model is None:
        # Reachable only if an enum value is added without registering a model.
        raise ValidationError(f"{request_type.value} requests are not accepted yet.")
    try:
        return model.model_validate(raw)
    except Exception as exc:
        raise ValidationError(f"That request could not be accepted: {exc}") from exc


# --- Codes -------------------------------------------------------------------


def generate_request_code(db: Session, *, year: int | None = None) -> str:
    """Sequential per-year code such as REQ-2026-0007."""
    year = year or utcnow().year
    prefix = f"REQ-{year}-"
    count = (
        db.scalar(
            select(func.count())
            .select_from(Request)
            .where(Request.request_code.startswith(prefix))
        )
        or 0
    )
    while True:
        candidate = f"{prefix}{count + 1:04d}"
        if db.scalar(select(Request.id).where(Request.request_code == candidate)) is None:
            return candidate
        count += 1


# --- Routing -----------------------------------------------------------------


def route(db: Session, *, employee: Employee) -> User | None:
    """Who should decide this request.

    Returns None today, meaning the HR/Admin pool: there is no manager role and
    Employee.reporting_manager is free text, so there is nobody specific to
    route to. When a manager hierarchy exists this is the only function that
    has to learn about it.
    """
    return None


# --- Permissions -------------------------------------------------------------


def can_decide(user: User, request: Request) -> bool:
    """May this user approve or reject this request?

    An approver may not decide their own request. An HR user submitting leave
    would otherwise land in the queue they themselves work, which is not an
    approval. Admin decides those instead.
    """
    if user.role not in (UserRole.HR, UserRole.ADMIN):
        return False
    if request.employee.user_id == user.id:
        return False
    return True


def owns(user: User, request: Request) -> bool:
    return request.employee.user_id == user.id


# --- Transitions -------------------------------------------------------------


def submit(
    db: Session,
    *,
    employee: Employee,
    request_type: RequestType,
    raw_payload: dict,
    actor: User,
) -> Request:
    """Create a pending request and tell the approvers about it."""
    payload = validate_payload(request_type, raw_payload)

    request = Request(
        request_code=generate_request_code(db),
        type=request_type,
        employee_id=employee.id,
        status=RequestStatus.PENDING,
        payload=payload.model_dump(mode="json"),
        summary=payload.summarise(),
        assigned_to_id=(assignee.id if (assignee := route(db, employee=employee)) else None),
    )
    db.add(request)
    db.flush()

    who = f"{employee.first_name} {employee.last_name}"
    notify_hr(
        db,
        type=NotificationType.REQUEST_SUBMITTED,
        title=f"{who} requested {payload.label.lower()}",
        body=request.summary,
        link=f"/approvals?request={request.request_code}",
        entity_type="request",
        entity_id=request.id,
        actor=actor,
        # An HR user's own request must not appear in their own queue as news.
        exclude=actor,
    )
    return request


def _decide(
    db: Session,
    *,
    request: Request,
    approved: bool,
    actor: User,
    note: str | None,
) -> Request:
    if not request.is_open:
        raise ConflictError(
            f"That request is already {request.status.value}; it cannot be decided again."
        )
    if not can_decide(actor, request):
        # Deliberately specific: an approver hitting their own request should
        # learn why, not think the system is broken.
        if owns(actor, request):
            raise PermissionDeniedError(
                "You cannot decide your own request. An admin will review it."
            )
        raise PermissionDeniedError("You cannot decide that request.")

    request.status = RequestStatus.APPROVED if approved else RequestStatus.REJECTED
    request.decided_at = utcnow()
    request.decided_by_id = actor.id
    request.decision_note = note

    recipient = employee_recipient(db, request.employee)
    if recipient is not None:
        notify(
            db,
            user=recipient,
            type=(
                NotificationType.REQUEST_APPROVED
                if approved
                else NotificationType.REQUEST_REJECTED
            ),
            title=f"Your request was {request.status.value}",
            body=(note or request.summary),
            link=f"/my-requests?request={request.request_code}",
            entity_type="request",
            entity_id=request.id,
            actor=actor,
        )
    return request


def approve(db: Session, *, request: Request, actor: User, note: str | None = None) -> Request:
    return _decide(db, request=request, approved=True, actor=actor, note=note)


def reject(db: Session, *, request: Request, actor: User, note: str) -> Request:
    """Rejection requires a note — "no" without a reason generates a follow-up."""
    if not note or not note.strip():
        raise ValidationError("A reason is required when rejecting a request.")
    return _decide(db, request=request, approved=False, actor=actor, note=note.strip())


def cancel(db: Session, *, request: Request, actor: User) -> Request:
    """Withdraw a request. Only the requester, and only before a decision."""
    if not owns(actor, request):
        raise PermissionDeniedError("You can only withdraw your own requests.")
    if not request.is_open:
        raise ConflictError(
            f"That request is already {request.status.value} and cannot be withdrawn."
        )
    request.status = RequestStatus.CANCELLED
    request.decided_at = utcnow()
    return request


# --- Queries -----------------------------------------------------------------


def for_employee(db: Session, *, employee_id: uuid.UUID) -> list[Request]:
    return list(
        db.scalars(
            select(Request)
            .where(Request.employee_id == employee_id)
            .order_by(Request.submitted_at.desc())
        ).unique()
    )


def queue(
    db: Session,
    *,
    status: RequestStatus | None = None,
    request_type: RequestType | None = None,
) -> list[Request]:
    """The approval queue. Oldest first — the longest wait is the most urgent."""
    filters = []
    if status is not None:
        filters.append(Request.status == status)
    if request_type is not None:
        filters.append(Request.type == request_type)
    return list(
        db.scalars(
            select(Request).where(*filters).order_by(Request.submitted_at)
        ).unique()
    )


def pending_count(db: Session) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Request)
            .where(Request.status == RequestStatus.PENDING)
        )
        or 0
    )
