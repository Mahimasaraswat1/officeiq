"""Notification request/response contracts (PRD A.7.7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import NotificationType


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: NotificationType
    title: str
    body: str | None = None
    link: str | None = Field(
        default=None, description="Frontend route this notification points at"
    )
    entity_type: str | None = None
    entity_id: str | None = None
    actor_name: str | None = Field(
        default=None, description="Who caused it; null when the system did"
    )
    is_read: bool
    read_at: datetime | None = None
    detail: dict | None = None
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int


class MarkedRead(BaseModel):
    marked_read: int


class ReminderRun(BaseModel):
    """What a reminder sweep actually created (it is idempotent, so often zero)."""

    due_soon: int
    overdue: int
