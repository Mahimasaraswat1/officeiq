"""HR dashboard and analytics (PRD A.9 / A.10 / B.4.7).

Read-only aggregates over data other phases already own. Nothing here computes a
number a different endpoint would answer differently — where a metric already
exists (chat resolution rate, task progress), this module runs the same
aggregation rather than a lookalike.

Day-bucketed trends are grouped in Python rather than SQL on purpose: date
truncation is spelled differently in Postgres and SQLite, and the window is
bounded (30 days by default), so the portable version costs nothing real.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.core.config import settings
from app.core.deps import DbSession, HrUser
from app.core.security import utcnow
from app.models.document import Document
from app.models.employee import Employee
from app.models.enums import (
    ChatOutcome,
    ChatRole,
    DocumentStatus,
    FaceMatchStatus,
    OnboardingStatus,
    TaskStatus,
    VerificationStatus,
)
from app.models.knowledge import ChatMessage, KnowledgeDocument
from app.models.task import EmployeeTask
from app.models.verification import FaceMatch, VerificationCheck
from app.schemas.dashboard import (
    AttentionGroup,
    AttentionQueue,
    DashboardSummary,
    DepartmentBreakdown,
    FailedCheck,
    FunnelStage,
    OnboardingFunnel,
    OverdueTask,
    PendingDocument,
    StalledOnboarding,
    TrendPoint,
    TrendSeries,
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

# Stages in the order an employee passes through them. REJECTED is deliberately
# absent: it is an exit, not a rung on the ladder, and drawing it as one makes
# the funnel read as though people flow into it.
FUNNEL_STAGES: list[tuple[OnboardingStatus, str]] = [
    (OnboardingStatus.INVITED, "Invited"),
    (OnboardingStatus.REGISTERED, "Registered"),
    (OnboardingStatus.DOCUMENTS_PENDING, "Documents pending"),
    (OnboardingStatus.DOCUMENTS_SUBMITTED, "Documents submitted"),
    (OnboardingStatus.UNDER_REVIEW, "Under review"),
    (OnboardingStatus.TASKS_ASSIGNED, "Tasks assigned"),
    (OnboardingStatus.COMPLETE, "Complete"),
]

_TERMINAL = (OnboardingStatus.COMPLETE, OnboardingStatus.REJECTED)


def _count(db: DbSession, model, *filters) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*filters)) or 0


# --- Summary ---------------------------------------------------------------


@router.get(
    "/summary", response_model=DashboardSummary, summary="Headline HR metrics (HR)"
)
def summary(
    db: DbSession,
    _: HrUser,
    days: Annotated[int, Query(ge=1, le=365)] = settings.DASHBOARD_TREND_DAYS,
) -> DashboardSummary:
    now = utcnow()
    window_start = now - timedelta(days=days)
    today = now.date()

    employees_total = _count(db, Employee)
    complete = _count(db, Employee, Employee.onboarding_status == OnboardingStatus.COMPLETE)
    rejected = _count(db, Employee, Employee.onboarding_status == OnboardingStatus.REJECTED)

    completed_in_window = _count(
        db,
        Employee,
        Employee.onboarding_completed_at.is_not(None),
        Employee.onboarding_completed_at >= window_start,
    )
    joining_soon = _count(
        db,
        Employee,
        Employee.date_of_joining.is_not(None),
        Employee.date_of_joining >= today,
        Employee.date_of_joining <= today + timedelta(days=30),
    )

    # Time-to-onboard, the PRD A.10 headline. Averaged in Python so the same
    # arithmetic runs on Postgres and SQLite.
    durations = [
        (completed_at - created_at).total_seconds() / 86400
        for created_at, completed_at in db.execute(
            select(Employee.created_at, Employee.onboarding_completed_at).where(
                Employee.onboarding_completed_at.is_not(None)
            )
        ).all()
        if completed_at is not None and created_at is not None
    ]
    average_days = round(sum(durations) / len(durations), 2) if durations else None

    # Task completion rate over every assigned task.
    task_rows = dict(
        db.execute(
            select(EmployeeTask.status, func.count()).group_by(EmployeeTask.status)
        ).all()
    )
    tasks_total = sum(task_rows.values())
    tasks_closed = task_rows.get(TaskStatus.COMPLETED, 0) + task_rows.get(TaskStatus.WAIVED, 0)
    tasks_open = tasks_total - tasks_closed
    tasks_overdue = _count(
        db,
        EmployeeTask,
        EmployeeTask.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]),
        EmployeeTask.due_date.is_not(None),
        EmployeeTask.due_date < today,
    )

    # Assistant resolution rate — the same aggregation /chat/analytics reports.
    chat_rows = dict(
        db.execute(
            select(ChatMessage.outcome, func.count())
            .where(ChatMessage.role == ChatRole.ASSISTANT, ChatMessage.outcome.is_not(None))
            .group_by(ChatMessage.outcome)
        ).all()
    )
    # Greetings are not questions; they belong in neither half of this ratio.
    chat_rows.pop(ChatOutcome.SMALL_TALK, None)
    questions_total = sum(chat_rows.values())
    answered = chat_rows.get(ChatOutcome.ANSWERED, 0)

    return DashboardSummary(
        employees_total=employees_total,
        onboarding_in_progress=employees_total - complete - rejected,
        onboarding_complete=complete,
        onboarding_rejected=rejected,
        completed_in_window=completed_in_window,
        joining_next_30_days=joining_soon,
        average_days_to_complete=average_days,
        documents_pending_review=_count(
            db, Document, Document.status == DocumentStatus.EXTRACTED
        ),
        documents_processing=_count(
            db,
            Document,
            Document.status.in_([DocumentStatus.UPLOADED, DocumentStatus.PROCESSING]),
        ),
        documents_failed=_count(db, Document, Document.status == DocumentStatus.FAILED),
        documents_approved=_count(db, Document, Document.status == DocumentStatus.APPROVED),
        documents_rejected=_count(db, Document, Document.status == DocumentStatus.REJECTED),
        verifications_failed=_count(
            db, VerificationCheck, VerificationCheck.status == VerificationStatus.FAILED
        ),
        face_matches_failed=_count(
            db, FaceMatch, FaceMatch.status != FaceMatchStatus.MATCHED
        ),
        tasks_open=tasks_open,
        tasks_overdue=tasks_overdue,
        task_completion_rate=round(tasks_closed / tasks_total, 4) if tasks_total else 0.0,
        questions_total=questions_total,
        chat_resolution_rate=(
            round(answered / questions_total, 4) if questions_total else 0.0
        ),
        knowledge_documents_published=_count(
            db, KnowledgeDocument, KnowledgeDocument.is_published.is_(True)
        ),
        window_days=days,
    )


# --- Funnel and breakdowns -------------------------------------------------


@router.get(
    "/funnel", response_model=OnboardingFunnel, summary="Onboarding funnel by stage (HR)"
)
def funnel(db: DbSession, _: HrUser) -> OnboardingFunnel:
    counts = dict(
        db.execute(
            select(Employee.onboarding_status, func.count()).group_by(
                Employee.onboarding_status
            )
        ).all()
    )
    return OnboardingFunnel(
        stages=[
            FunnelStage(status=status, label=label, count=counts.get(status, 0))
            for status, label in FUNNEL_STAGES
        ],
        total=sum(counts.values()),
    )


@router.get(
    "/departments",
    response_model=list[DepartmentBreakdown],
    summary="Headcount and progress by department (HR)",
)
def departments(db: DbSession, _: HrUser) -> list[DepartmentBreakdown]:
    rows = db.execute(
        select(Employee.department, Employee.onboarding_status, func.count()).group_by(
            Employee.department, Employee.onboarding_status
        )
    ).all()

    tally: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "complete": 0, "in_progress": 0})
    for department, status, count in rows:
        # Employees created before a department is known still have to appear
        # somewhere, or the breakdown silently omits people.
        bucket = tally[department or "Unassigned"]
        bucket["total"] += count
        if status is OnboardingStatus.COMPLETE:
            bucket["complete"] += count
        elif status is not OnboardingStatus.REJECTED:
            bucket["in_progress"] += count

    return [
        DepartmentBreakdown(department=name, **values)
        for name, values in sorted(tally.items(), key=lambda kv: -kv[1]["total"])
    ]


# --- Trends ----------------------------------------------------------------


def _bucket(stamps: list[datetime | None], start: date, span: int) -> dict[date, int]:
    counts: dict[date, int] = defaultdict(int)
    for stamp in stamps:
        if stamp is None:
            continue
        day = stamp.date()
        if start <= day <= start + timedelta(days=span - 1):
            counts[day] += 1
    return counts


@router.get(
    "/trends", response_model=TrendSeries, summary="Daily activity over a window (HR)"
)
def trends(
    db: DbSession,
    _: HrUser,
    days: Annotated[int, Query(ge=1, le=365)] = settings.DASHBOARD_TREND_DAYS,
) -> TrendSeries:
    now = utcnow()
    window_start = now - timedelta(days=days - 1)
    start_day = window_start.date()

    def stamps(column, *filters) -> list[datetime | None]:
        return list(
            db.scalars(select(column).where(column >= window_start, *filters)).all()
        )

    created = _bucket(stamps(Employee.created_at), start_day, days)
    completed = _bucket(stamps(Employee.onboarding_completed_at), start_day, days)
    uploaded = _bucket(stamps(Document.created_at), start_day, days)
    questions = _bucket(
        stamps(ChatMessage.created_at, ChatMessage.role == ChatRole.USER), start_day, days
    )
    # Registration has no timestamp of its own; the accepted invitation carries it.
    from app.models.employee import Invitation
    from app.models.enums import InvitationStatus

    registered = _bucket(
        stamps(Invitation.accepted_at, Invitation.status == InvitationStatus.ACCEPTED),
        start_day,
        days,
    )

    points = []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        points.append(
            TrendPoint(
                date=day,
                profiles_created=created.get(day, 0),
                registrations=registered.get(day, 0),
                completions=completed.get(day, 0),
                documents_uploaded=uploaded.get(day, 0),
                questions_asked=questions.get(day, 0),
            )
        )

    return TrendSeries(points=points, days=days)


# --- Attention queue -------------------------------------------------------


@router.get(
    "/attention",
    response_model=AttentionQueue,
    summary="What needs a human right now (HR)",
)
def attention(
    db: DbSession,
    _: HrUser,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> AttentionQueue:
    """The dashboard's action list: four queues, each newest-problem-first.

    Every group reports its true `total` alongside the capped `items`, so a
    backlog longer than the cap is visible rather than quietly truncated.
    """
    now = utcnow()
    today = now.date()

    # 1. Documents whose extraction finished and now need an HR decision.
    pending_filter = (Document.status == DocumentStatus.EXTRACTED,)
    pending_rows = db.execute(
        select(Document, Employee)
        .join(Employee, Document.employee_id == Employee.id)
        .where(*pending_filter)
        .order_by(Document.created_at.asc())  # oldest waited longest
        .limit(limit)
    ).all()
    pending = AttentionGroup[PendingDocument](
        total=_count(db, Document, *pending_filter),
        items=[
            PendingDocument(
                document_id=doc.id,
                employee_id=emp.id,
                employee_name=emp.full_name,
                document_type=doc.document_type,
                original_filename=doc.original_filename,
                uploaded_at=doc.created_at,
                days_waiting=(now - doc.created_at).days,
            )
            for doc, emp in pending_rows
        ],
    )

    # 2. ID checks the mock registry rejected.
    failed_filter = (VerificationCheck.status == VerificationStatus.FAILED,)
    failed_rows = db.execute(
        select(VerificationCheck, Employee)
        .join(Employee, VerificationCheck.employee_id == Employee.id)
        .where(*failed_filter)
        .order_by(VerificationCheck.created_at.desc())
        .limit(limit)
    ).all()
    failed = AttentionGroup[FailedCheck](
        total=_count(db, VerificationCheck, *failed_filter),
        items=[
            FailedCheck(
                employee_id=emp.id,
                employee_name=emp.full_name,
                check_type=check.check_type.value,
                reason_code=check.reason_code,
                message=check.message,
                occurred_at=check.created_at,
            )
            for check, emp in failed_rows
        ],
    )

    # 3. Open tasks past their due date.
    overdue_filter = (
        EmployeeTask.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]),
        EmployeeTask.due_date.is_not(None),
        EmployeeTask.due_date < today,
    )
    overdue_rows = db.execute(
        select(EmployeeTask, Employee)
        .join(Employee, EmployeeTask.employee_id == Employee.id)
        .where(*overdue_filter)
        .order_by(EmployeeTask.due_date.asc())
        .limit(limit)
    ).all()
    overdue = AttentionGroup[OverdueTask](
        total=_count(db, EmployeeTask, *overdue_filter),
        items=[
            OverdueTask(
                task_id=task.id,
                employee_id=emp.id,
                employee_name=emp.full_name,
                title=task.title,
                due_date=task.due_date,
                days_overdue=(today - task.due_date).days,
                is_mandatory=task.is_mandatory,
            )
            for task, emp in overdue_rows
        ],
    )

    # 4. Onboardings that have not moved in a while — the ones nobody is chasing.
    cutoff = now - timedelta(days=settings.ONBOARDING_STALLED_DAYS)
    stalled_filter = (
        Employee.onboarding_status.not_in(_TERMINAL),
        Employee.updated_at < cutoff,
    )
    stalled_rows = db.scalars(
        select(Employee)
        .where(*stalled_filter)
        .order_by(Employee.updated_at.asc())
        .limit(limit)
    ).all()
    stalled = AttentionGroup[StalledOnboarding](
        total=_count(db, Employee, *stalled_filter),
        items=[
            StalledOnboarding(
                employee_id=emp.id,
                employee_name=emp.full_name,
                onboarding_status=emp.onboarding_status,
                days_since_update=(now - emp.updated_at).days,
            )
            for emp in stalled_rows
        ],
    )

    return AttentionQueue(
        documents_pending_review=pending,
        failed_verifications=failed,
        overdue_tasks=overdue,
        stalled_onboardings=stalled,
        limit=limit,
    )
