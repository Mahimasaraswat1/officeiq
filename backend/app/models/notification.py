"""In-app notifications (PRD A.7.7 / B.4.6).

One row per recipient per event. Fanning out at write time rather than deriving
a feed at read time keeps "is this read?" a property of the person who received
it, and leaves the notification text as it was worded when the event happened —
a later rename of a document or task never rewrites someone's inbox.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Enum as SAEnum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.core.database import Base
from app.core.types import TZDateTime
from app.models.enums import NotificationType
from app.models.user import User

json_type = JSON().with_variant(JSONB(), "postgresql")

notification_type_enum = SAEnum(
    NotificationType,
    name="notification_type",
    values_callable=lambda e: [m.value for m in e],
)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        # The unread badge and the inbox are the only two read paths, and both
        # filter by recipient and sort by recency.
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    type: Mapped[NotificationType] = mapped_column(
        notification_type_enum, nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    # A frontend route, e.g. "/employees/{id}". Relative by design — the API
    # does not decide where the UI lives.
    link: Mapped[str | None] = mapped_column(String(512))

    # What the notification is about, so a repeat event can find its predecessor.
    entity_type: Mapped[str | None] = mapped_column(String(64), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)

    # Who caused it. NULL when the system did (a background verification run).
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_name: Mapped[str | None] = mapped_column(String(150))

    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    detail: Mapped[dict | None] = mapped_column(json_type)

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), index=True, nullable=False
    )

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    actor: Mapped[User | None] = relationship(foreign_keys=[actor_user_id])

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Notification {self.type.value} -> {self.user_id}>"
