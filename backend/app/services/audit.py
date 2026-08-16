"""Helper for writing append-only audit entries (PRD A.7.9 / B.4.8)."""

from __future__ import annotations

import uuid

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.enums import AuditAction
from app.models.user import User


def client_ip(request: Request | None) -> str | None:
    """The caller's IP, honouring a proxy's X-Forwarded-For."""
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else None


def record_audit(
    db: Session,
    *,
    action: AuditAction,
    actor: User | None = None,
    actor_email: str | None = None,
    entity_type: str | None = None,
    entity_id: str | uuid.UUID | None = None,
    detail: dict | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Stage an audit row on the session. The caller owns the commit."""
    entry = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_email=(actor.email if actor else actor_email),
        actor_role=(actor.role.value if actor else None),
        action=action.value,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent", "")[:255] if request else None) or None,
        detail=detail,
    )
    db.add(entry)
    return entry
