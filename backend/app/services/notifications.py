"""Notification fan-out (PRD A.7.7 / B.4.6).

Every function here *stages* rows on the session and leaves the commit to the
caller, exactly like `record_audit`. That matters: a notification saying "your
document was approved" must not survive a transaction that failed to approve
the document.

Delivery is in-app first. When `NOTIFICATION_EMAIL_ENABLED` is set, employee-facing
events are also emailed through the existing pluggable backend, so turning on real
email is configuration rather than code.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import utcnow, today_utc
from app.models.document import Document
from app.models.employee import Employee
from app.models.enums import (
    DocumentStatus,
    NotificationType,
    TaskStatus,
    UserRole,
)
from app.models.notification import Notification
from app.models.task import EmployeeTask
from app.models.user import User
from app.services.email import send_email

logger = logging.getLogger(__name__)

# Events worth an email as well as a bell badge. HR-facing events are excluded:
# HR lives in the app, and a mailbox full of "a document was uploaded" is noise.
_EMAILABLE = {
    NotificationType.DOCUMENT_REJECTED,
    NotificationType.TASKS_ASSIGNED,
    NotificationType.TASK_OVERDUE,
    NotificationType.ONBOARDING_COMPLETE,
}


# --- Recipient resolution --------------------------------------------------


def hr_recipients(db: Session) -> list[User]:
    """Every active HR and Admin user — the audience for operational events."""
    return list(
        db.scalars(
            select(User).where(
                User.is_active.is_(True),
                User.role.in_([UserRole.HR, UserRole.ADMIN]),
            )
        ).all()
    )


def employee_recipient(db: Session, employee: Employee) -> User | None:
    """The employee's login, or None if they have not registered yet.

    An unregistered employee has nowhere to receive a notification, so callers
    silently skip rather than queueing something nobody can read.
    """
    if employee.user_id is None:
        return None
    return db.get(User, employee.user_id)


# --- Core writer -----------------------------------------------------------


def notify(
    db: Session,
    *,
    user: User,
    type: NotificationType,
    title: str,
    body: str | None = None,
    link: str | None = None,
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    actor: User | None = None,
    detail: dict | None = None,
) -> Notification:
    """Stage one notification for one recipient."""
    notification = Notification(
        user_id=user.id,
        type=type,
        title=title[:200],
        body=body,
        link=link,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        actor_user_id=actor.id if actor else None,
        actor_name=actor.full_name if actor else None,
        detail=detail,
    )
    db.add(notification)

    if settings.NOTIFICATION_EMAIL_ENABLED and type in _EMAILABLE:
        # send_email swallows its own failures, so delivery trouble never
        # rolls back the event that caused it.
        send_email(
            to=user.email,
            subject=title,
            body=(
                f"Hi {user.full_name},\n\n"
                f"{body or title}\n\n"
                f"{settings.FRONTEND_BASE_URL}{link or '/'}\n\n"
                "— The OfficeIQ Team"
            ),
        )
    return notification


def notify_once(
    db: Session,
    *,
    user: User,
    type: NotificationType,
    entity_id: str | uuid.UUID | None,
    **kwargs: object,
) -> Notification | None:
    """Stage a notification unless an unread one already covers the same thing.

    Reminders are re-run on a schedule; without this an overdue task would
    produce a fresh row on every sweep and bury everything else in the inbox.
    Once the recipient reads it, a later sweep may legitimately remind again.
    """
    existing = db.scalar(
        select(Notification).where(
            Notification.user_id == user.id,
            Notification.type == type,
            Notification.entity_id == (str(entity_id) if entity_id is not None else None),
            Notification.is_read.is_(False),
        )
    )
    if existing is not None:
        return None
    return notify(db, user=user, type=type, entity_id=entity_id, **kwargs)  # type: ignore[arg-type]


def notify_hr(
    db: Session,
    *,
    type: NotificationType,
    title: str,
    exclude: User | None = None,
    **kwargs: object,
) -> list[Notification]:
    """Fan an operational event out to every HR/Admin user.

    `exclude` drops the person who caused it — telling HR about their own click
    is noise, not news.
    """
    created = []
    for recipient in hr_recipients(db):
        if exclude is not None and recipient.id == exclude.id:
            continue
        created.append(notify(db, user=recipient, type=type, title=title, **kwargs))  # type: ignore[arg-type]
    return created


# --- Event helpers ---------------------------------------------------------


def notify_document_uploaded(
    db: Session, *, document: Document, actor: User | None = None
) -> None:
    employee = document.employee
    notify_hr(
        db,
        type=NotificationType.DOCUMENT_UPLOADED,
        title=f"{employee.full_name} uploaded a {document.document_type.value} document",
        body=f"{document.original_filename} is ready for review once extraction finishes.",
        link=f"/employees/{employee.id}",
        entity_type="document",
        entity_id=document.id,
        actor=actor,
        exclude=actor,
        detail={"document_type": document.document_type.value},
    )


def notify_document_decision(
    db: Session, *, document: Document, actor: User | None = None
) -> None:
    """Tell the employee that HR approved or rejected one of their documents."""
    recipient = employee_recipient(db, document.employee)
    if recipient is None:
        return

    approved = document.status is DocumentStatus.APPROVED
    label = document.document_type.value
    if approved:
        notify(
            db,
            user=recipient,
            type=NotificationType.DOCUMENT_APPROVED,
            title=f"Your {label} document was approved",
            body=document.rejection_reason or None,
            link="/my-onboarding",
            entity_type="document",
            entity_id=document.id,
            actor=actor,
            detail={"document_type": label},
        )
    else:
        notify(
            db,
            user=recipient,
            type=NotificationType.DOCUMENT_REJECTED,
            title=f"Your {label} document needs attention",
            # The reason is the whole point of the notification — it is what
            # tells the employee what to fix (PRD A.7.4).
            body=document.rejection_reason,
            link="/my-onboarding",
            entity_type="document",
            entity_id=document.id,
            actor=actor,
            detail={"document_type": label, "reason": document.rejection_reason},
        )


def notify_tasks_assigned(
    db: Session, *, employee: Employee, count: int, actor: User | None = None
) -> None:
    if count <= 0:
        return
    recipient = employee_recipient(db, employee)
    if recipient is None:
        return
    notify(
        db,
        user=recipient,
        type=NotificationType.TASKS_ASSIGNED,
        title=f"{count} onboarding {'task' if count == 1 else 'tasks'} assigned to you",
        body="Your onboarding checklist is ready. Mandatory items must be completed "
        "before onboarding can be marked complete.",
        link="/my-tasks",
        entity_type="employee",
        entity_id=employee.id,
        actor=actor,
        detail={"count": count},
    )


def notify_onboarding_complete(
    db: Session, *, employee: Employee, actor: User | None = None
) -> None:
    recipient = employee_recipient(db, employee)
    if recipient is not None:
        notify(
            db,
            user=recipient,
            type=NotificationType.ONBOARDING_COMPLETE,
            title="Your onboarding is complete",
            body="Everything is signed off. Welcome aboard!",
            link="/",
            entity_type="employee",
            entity_id=employee.id,
            actor=actor,
        )
    notify_hr(
        db,
        type=NotificationType.ONBOARDING_COMPLETE,
        title=f"{employee.full_name} finished onboarding",
        link=f"/employees/{employee.id}",
        entity_type="employee",
        entity_id=employee.id,
        actor=actor,
        exclude=actor,
    )


def notify_invitation_accepted(db: Session, *, employee: Employee) -> None:
    notify_hr(
        db,
        type=NotificationType.INVITATION_ACCEPTED,
        title=f"{employee.full_name} accepted their invitation",
        body="Their account is active and they can start uploading documents.",
        link=f"/employees/{employee.id}",
        entity_type="employee",
        entity_id=employee.id,
    )


def notify_verification_failed(
    db: Session, *, employee: Employee, check_type: str, reason: str, message: str | None
) -> None:
    """Flag a failed ID check to HR — a decision only a person can make."""
    notify_hr(
        db,
        type=NotificationType.VERIFICATION_FAILED,
        title=f"{check_type.upper()} verification failed for {employee.full_name}",
        body=message,
        link=f"/employees/{employee.id}",
        entity_type="employee",
        entity_id=employee.id,
        detail={"check_type": check_type, "reason": reason},
    )


def notify_chat_escalated(
    db: Session, *, asker: User, question: str, reason: str
) -> None:
    """Route an unanswerable policy question to HR.

    Only the question is shared, never the conversation — HR reading transcripts
    is exactly what the Phase 5 privacy boundary forbids.
    """
    notify_hr(
        db,
        type=NotificationType.CHAT_ESCALATED,
        title=f"{asker.full_name} asked a question the assistant could not answer",
        body=question[:500],
        link="/knowledge-base",
        entity_type="user",
        entity_id=asker.id,
        detail={"reason": reason},
    )


# --- Scheduled reminders ---------------------------------------------------


def run_task_reminders(db: Session, *, today: date | None = None) -> dict[str, int]:
    """Raise due-soon and overdue reminders for open mandatory tasks.

    Idempotent by way of `notify_once`, so a scheduler may call this as often as
    it likes. Returns per-type counts of what was actually created.
    """
    today = today or today_utc()
    horizon = today + timedelta(days=settings.TASK_DUE_SOON_DAYS)

    open_tasks = db.scalars(
        select(EmployeeTask).where(
            EmployeeTask.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]),
            EmployeeTask.due_date.is_not(None),
            EmployeeTask.due_date <= horizon,
        )
    ).all()

    counts = {"due_soon": 0, "overdue": 0}
    for task in open_tasks:
        recipient = employee_recipient(db, task.employee)
        if recipient is None:
            continue

        overdue = task.due_date < today
        created = notify_once(
            db,
            user=recipient,
            type=(
                NotificationType.TASK_OVERDUE if overdue else NotificationType.TASK_DUE_SOON
            ),
            entity_id=task.id,
            title=(
                f"Overdue: {task.title}" if overdue else f"Due soon: {task.title}"
            ),
            body=(
                f"This task was due on {task.due_date:%d %b %Y}."
                if overdue
                else f"This task is due on {task.due_date:%d %b %Y}."
            ),
            link="/my-tasks",
            entity_type="task",
            detail={"due_date": task.due_date.isoformat(), "mandatory": task.is_mandatory},
        )
        if created is not None:
            counts["overdue" if overdue else "due_soon"] += 1

    return counts


# --- Reads -----------------------------------------------------------------


def unread_count(db: Session, user: User) -> int:
    from sqlalchemy import func

    return (
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        )
        or 0
    )


def mark_all_read(db: Session, user: User) -> int:
    """Mark every unread notification read. Returns how many changed."""
    rows = db.scalars(
        select(Notification).where(
            Notification.user_id == user.id, Notification.is_read.is_(False)
        )
    ).all()
    now = utcnow()
    for row in rows:
        row.is_read = True
        row.read_at = now
    return len(rows)
