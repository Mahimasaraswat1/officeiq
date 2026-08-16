"""Append-only audit log (PRD A.7.9 / B.4.8).

Rows are only ever INSERTed — no update or delete path exists in the codebase,
and no API surface exposes one.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.core.database import Base
from app.core.types import TZDateTime
from app.models.user import User

# JSONB on Postgres, plain JSON elsewhere (e.g. SQLite in tests).
json_type = JSON().with_variant(JSONB(), "postgresql")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Denormalised so the trail survives user deletion.
    actor_email: Mapped[str | None] = mapped_column(String(255))
    actor_role: Mapped[str | None] = mapped_column(String(32))

    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True)

    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    detail: Mapped[dict | None] = mapped_column(json_type)

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), index=True, nullable=False
    )

    actor: Mapped[User | None] = relationship()
