"""HR dashboard and analytics contracts (PRD A.9 / A.10 / B.4.7)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

from app.models.enums import DocumentType, OnboardingStatus

T = TypeVar("T")


class DashboardSummary(BaseModel):
    """Headline numbers for the HR landing page."""

    # --- People ------------------------------------------------------------
    employees_total: int
    onboarding_in_progress: int = Field(
        description="Neither complete nor rejected — someone is still working through it"
    )
    onboarding_complete: int
    onboarding_rejected: int
    completed_in_window: int = Field(description="Completions inside the trend window")
    joining_next_30_days: int
    average_days_to_complete: float | None = Field(
        default=None,
        description="Mean calendar days from profile creation to completion; "
        "null until at least one onboarding has completed",
    )

    # --- Documents ---------------------------------------------------------
    documents_pending_review: int = Field(
        description="Extraction finished, waiting on an HR decision"
    )
    documents_processing: int
    documents_failed: int
    documents_approved: int
    documents_rejected: int

    # --- Verification ------------------------------------------------------
    verifications_failed: int
    face_matches_failed: int

    # --- Tasks -------------------------------------------------------------
    tasks_open: int
    tasks_overdue: int
    task_completion_rate: float = Field(
        description="Closed (completed or waived) over all assigned tasks, 0.0-1.0"
    )

    # --- Assistant ---------------------------------------------------------
    questions_total: int
    chat_resolution_rate: float = Field(
        description="Answered without escalation, 0.0-1.0 (PRD A.10)"
    )
    knowledge_documents_published: int

    window_days: int


class FunnelStage(BaseModel):
    status: OnboardingStatus
    label: str
    count: int


class OnboardingFunnel(BaseModel):
    stages: list[FunnelStage]
    total: int


class DepartmentBreakdown(BaseModel):
    department: str
    total: int
    complete: int
    in_progress: int


class TrendPoint(BaseModel):
    date: date
    profiles_created: int
    registrations: int
    completions: int
    documents_uploaded: int
    questions_asked: int


class TrendSeries(BaseModel):
    points: list[TrendPoint]
    days: int


class PendingDocument(BaseModel):
    document_id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    document_type: DocumentType
    original_filename: str
    uploaded_at: datetime
    days_waiting: int


class FailedCheck(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    check_type: str
    reason_code: str | None = None
    message: str | None = None
    occurred_at: datetime


class OverdueTask(BaseModel):
    task_id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    title: str
    due_date: date
    days_overdue: int
    is_mandatory: bool


class StalledOnboarding(BaseModel):
    employee_id: uuid.UUID
    employee_name: str
    onboarding_status: OnboardingStatus
    days_since_update: int


class AttentionGroup(BaseModel, Generic[T]):
    """A work queue, capped for display.

    `total` is the real size and `items` may be shorter — the UI says so rather
    than implying an empty backlog once the cap is hit.
    """

    total: int
    items: list[T]


class AttentionQueue(BaseModel):
    documents_pending_review: AttentionGroup[PendingDocument]
    failed_verifications: AttentionGroup[FailedCheck]
    overdue_tasks: AttentionGroup[OverdueTask]
    stalled_onboardings: AttentionGroup[StalledOnboarding]
    limit: int
