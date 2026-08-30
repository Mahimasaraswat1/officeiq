"""Request & approval contracts."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RequestStatus, RequestType


class RequestCreate(BaseModel):
    """Submit a request.

    `payload` is intentionally an open dict: its shape depends on `type` and is
    validated server-side against that type's registered model. Typing it here
    per type would put the registry in two places.
    """

    type: RequestType
    payload: dict = Field(description="Type-specific fields; see the type's payload model")


class RequestDecision(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class RequestRejection(BaseModel):
    """Rejecting requires a reason — the employee has to know what to fix."""

    note: str = Field(min_length=1, max_length=2000)


class RequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    request_code: str
    type: RequestType
    status: RequestStatus
    payload: dict
    summary: str

    employee_id: uuid.UUID
    employee_name: str
    employee_code: str

    submitted_at: datetime
    decided_at: datetime | None = None
    decided_by_name: str | None = None
    decision_note: str | None = None

    # Whether *this* viewer can act, so the UI does not have to re-derive the
    # self-approval rule and drift from the server's answer.
    can_decide: bool = False
    can_cancel: bool = False


class RequestCounts(BaseModel):
    pending: int
    approved: int
    rejected: int
    cancelled: int
