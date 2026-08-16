"""In-app notification inbox (PRD A.7.7 / B.4.6).

Notifications are strictly per-recipient: every route here is scoped to the
signed-in user's own rows, so there is no "read someone else's inbox" path for
any role, Admin included.
"""

from __future__ import annotations

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, HrUser
from app.core.errors import NotFoundError
from app.core.security import utcnow
from app.models.enums import AuditAction, NotificationType
from app.models.notification import Notification
from app.schemas.common import Message, Page
from app.schemas.notification import (
    MarkedRead,
    NotificationRead,
    ReminderRun,
    UnreadCount,
)
from app.services.audit import record_audit
from app.services.notifications import mark_all_read, run_task_reminders, unread_count

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def _get_own_or_404(db: DbSession, notification_id: uuid.UUID, user_id: uuid.UUID) -> Notification:
    """Fetch by id *and* owner, so a wrong guess is indistinguishable from a
    missing row — an id belonging to someone else must not confirm it exists."""
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
    )
    if notification is None:
        raise NotFoundError("Notification not found.")
    return notification


@router.get("", response_model=Page[NotificationRead], summary="My notifications")
def list_notifications(
    db: DbSession,
    user: CurrentUser,
    unread_only: bool = False,
    type: NotificationType | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[NotificationRead]:
    filters = [Notification.user_id == user.id]
    if unread_only:
        filters.append(Notification.is_read.is_(False))
    if type is not None:
        filters.append(Notification.type == type)

    total = db.scalar(select(func.count()).select_from(Notification).where(*filters)) or 0
    rows = db.scalars(
        select(Notification)
        .where(*filters)
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return Page[NotificationRead](
        items=[NotificationRead.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get(
    "/unread-count",
    response_model=UnreadCount,
    summary="How many unread notifications I have",
)
def get_unread_count(db: DbSession, user: CurrentUser) -> UnreadCount:
    return UnreadCount(unread=unread_count(db, user))


@router.post(
    "/read-all", response_model=MarkedRead, summary="Mark all my notifications read"
)
def read_all(request: Request, db: DbSession, user: CurrentUser) -> MarkedRead:
    count = mark_all_read(db, user)
    if count:
        record_audit(
            db,
            action=AuditAction.NOTIFICATIONS_MARKED_READ,
            actor=user,
            entity_type="user",
            entity_id=user.id,
            detail={"count": count},
            request=request,
        )
    db.commit()
    return MarkedRead(marked_read=count)


@router.post(
    "/{notification_id}/read",
    response_model=NotificationRead,
    summary="Mark one notification read",
)
def read_one(
    notification_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> NotificationRead:
    notification = _get_own_or_404(db, notification_id, user.id)
    # Re-reading is a no-op rather than an error; the UI fires this on click.
    if not notification.is_read:
        notification.is_read = True
        notification.read_at = utcnow()
        db.commit()
        db.refresh(notification)
    return NotificationRead.model_validate(notification)


@router.delete("/{notification_id}", response_model=Message, summary="Dismiss a notification")
def dismiss(notification_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Message:
    notification = _get_own_or_404(db, notification_id, user.id)
    db.delete(notification)
    db.commit()
    return Message(message="Notification dismissed.")


@router.post(
    "/run-reminders",
    response_model=ReminderRun,
    summary="Raise due-soon and overdue task reminders (HR)",
)
def run_reminders(request: Request, db: DbSession, actor: HrUser) -> ReminderRun:
    """The hook a scheduler calls (cron, Celery beat, a platform job).

    Exposed as an endpoint rather than buried in a worker so the behaviour is
    testable and HR can trigger a sweep by hand. Idempotent: a recipient who
    already has an unread reminder for a task does not get a second one.
    """
    counts = run_task_reminders(db)
    record_audit(
        db,
        action=AuditAction.REMINDERS_RUN,
        actor=actor,
        entity_type="notification",
        detail=counts,
        request=request,
    )
    db.commit()
    return ReminderRun(**counts)
