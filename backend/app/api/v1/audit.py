"""Read-only audit trail (PRD A.7.9 / B.4.8).

The table is append-only: there is no update or delete path anywhere in the
codebase, and none is exposed here. Everything below is a filtered read.

`build_audit_filters` is shared with the audit-trail report so the export and
the on-screen list can never disagree about what a filter means.
"""

from __future__ import annotations

import math
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select

from app.core.deps import AdminUser, DbSession
from app.core.errors import NotFoundError
from app.models.audit import AuditLog
from app.schemas.common import Page

router = APIRouter(prefix="/audit-logs", tags=["Audit"])


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_user_id: uuid.UUID | None = None
    actor_email: str | None = None
    actor_role: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    detail: dict | None = None
    created_at: datetime


class AuditFacets(BaseModel):
    """The values actually present, so filter dropdowns offer real options."""

    actions: list[str]
    entity_types: list[str]
    actors: list[str]
    total: int


def build_audit_filters(
    *,
    action: str | None = None,
    actor: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list:
    filters = []
    if action:
        filters.append(AuditLog.action == action)
    if actor:
        # Substring, because you rarely recall an exact address.
        filters.append(func.lower(AuditLog.actor_email).like(f"%{actor.strip().lower()}%"))
    if entity_type:
        filters.append(AuditLog.entity_type == entity_type)
    if entity_id:
        filters.append(AuditLog.entity_id == str(entity_id))
    if date_from:
        filters.append(
            AuditLog.created_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        )
    if date_to:
        # Inclusive of the whole end day — "to 5 March" must include 5 March.
        filters.append(
            AuditLog.created_at
            < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
        )
    return filters


@router.get("", response_model=Page[AuditLogRead], summary="List audit entries (Admin)")
def list_audit_logs(
    db: DbSession,
    _: AdminUser,
    action: Annotated[str | None, Query(description="Exact action, e.g. login_success")] = None,
    actor: Annotated[str | None, Query(description="Substring of the actor's email")] = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    date_from: Annotated[date | None, Query(description="Inclusive start date (UTC)")] = None,
    date_to: Annotated[date | None, Query(description="Inclusive end date (UTC)")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[AuditLogRead]:
    filters = build_audit_filters(
        action=action,
        actor=actor,
        entity_type=entity_type,
        entity_id=entity_id,
        date_from=date_from,
        date_to=date_to,
    )

    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    rows = db.scalars(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    return Page[AuditLogRead](
        items=[AuditLogRead.model_validate(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        pages=math.ceil(total / page_size) if total else 0,
    )


@router.get(
    "/facets",
    response_model=AuditFacets,
    summary="Distinct actions, entities and actors present (Admin)",
)
def facets(db: DbSession, _: AdminUser) -> AuditFacets:
    """Drives the filter dropdowns.

    Derived from the data rather than from the AuditAction enum: an action the
    system has never recorded would be a dead option, and an action written by
    an older build would be missing from a hard-coded list.
    """
    actions = db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action)).all()
    entity_types = db.scalars(
        select(AuditLog.entity_type)
        .where(AuditLog.entity_type.is_not(None))
        .distinct()
        .order_by(AuditLog.entity_type)
    ).all()
    actors = db.scalars(
        select(AuditLog.actor_email)
        .where(AuditLog.actor_email.is_not(None))
        .distinct()
        .order_by(AuditLog.actor_email)
        .limit(200)
    ).all()
    total = db.scalar(select(func.count()).select_from(AuditLog)) or 0

    return AuditFacets(
        actions=list(actions),
        entity_types=list(entity_types),
        actors=list(actors),
        total=total,
    )


@router.get(
    "/{entry_id}", response_model=AuditLogRead, summary="One audit entry in full (Admin)"
)
def get_audit_entry(entry_id: uuid.UUID, db: DbSession, _: AdminUser) -> AuditLogRead:
    entry = db.get(AuditLog, entry_id)
    if entry is None:
        raise NotFoundError("Audit entry not found.")
    return AuditLogRead.model_validate(entry)
