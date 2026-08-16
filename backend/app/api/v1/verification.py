"""Mock ID verification, face matching, and the HR review workflow (PRD A.7.4)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, HrUser
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.security import utcnow
from app.models.document import Document
from app.models.employee import Employee
from app.models.enums import (
    AuditAction,
    DocumentStatus,
    DocumentType,
    FaceMatchStatus,
    OnboardingStatus,
    UserRole,
    VerificationStatus,
)
from app.models.user import User
from app.models.verification import FaceMatch, VerificationCheck
from app.schemas.verification import (
    DocumentRejectRequest,
    DocumentReviewRequest,
    DocumentReviewResult,
    FaceMatchRead,
    VerificationCheckRead,
    VerificationSummary,
)
from app.services.assignment import compute_progress, sync_document_checklist
from app.services.audit import record_audit
from app.services.notifications import (
    notify_document_decision,
    notify_onboarding_complete,
)
from app.services.review import (
    REQUIRED_DOCUMENT_TYPES,
    VERIFIABLE_TYPES,
    recalculate_onboarding_status,
    run_face_match,
    run_id_verification,
)

router = APIRouter(tags=["Verification & Review"])


def _get_employee_or_404(db: DbSession, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Employee not found.")
    return employee


def _get_document_or_404(db: DbSession, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Document not found.")
    return document


def _assert_can_view(employee: Employee, user: User) -> None:
    if user.role in (UserRole.ADMIN, UserRole.HR):
        return
    if employee.user_id != user.id:
        raise PermissionDeniedError("You can only access your own verification results.")


# --- Running checks --------------------------------------------------------


@router.post(
    "/documents/{document_id}/verify",
    response_model=VerificationCheckRead,
    status_code=status.HTTP_201_CREATED,
    summary="Run the mock Aadhaar/PAN check for a document",
)
def verify_document(
    document_id: uuid.UUID, request: Request, db: DbSession, actor: HrUser
) -> VerificationCheckRead:
    document = _get_document_or_404(db, document_id)

    if document.document_type not in VERIFIABLE_TYPES:
        raise ValidationError(
            f"A {document.document_type.value} document carries no ID number to verify."
        )
    if document.status is DocumentStatus.UPLOADED or document.status is DocumentStatus.PROCESSING:
        raise ConflictError("Wait for extraction to finish before running verification.")

    check = run_id_verification(db, document=document, actor=actor)
    recalculate_onboarding_status(db, document.employee, actor=actor)
    db.commit()
    db.refresh(check)
    return VerificationCheckRead.model_validate(check)


@router.post(
    "/employees/{employee_id}/face-match",
    response_model=FaceMatchRead,
    status_code=status.HTTP_201_CREATED,
    summary="Compare the employee photo against their ID document",
)
def run_employee_face_match(
    employee_id: uuid.UUID, request: Request, db: DbSession, actor: HrUser
) -> FaceMatchRead:
    employee = _get_employee_or_404(db, employee_id)

    match = run_face_match(db, employee=employee, actor=actor)
    if match is None:
        raise ConflictError(
            "Face matching needs both a photo and an Aadhaar or PAN document. "
            "Ask the employee to upload whichever is missing."
        )

    recalculate_onboarding_status(db, employee, actor=actor)
    db.commit()
    db.refresh(match)
    return FaceMatchRead.model_validate(match)


# --- Reading results -------------------------------------------------------


@router.get(
    "/employees/{employee_id}/verifications",
    response_model=list[VerificationCheckRead],
    summary="ID verification history for an employee",
)
def list_verifications(
    employee_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[VerificationCheckRead]:
    employee = _get_employee_or_404(db, employee_id)
    _assert_can_view(employee, user)

    rows = db.scalars(
        select(VerificationCheck)
        .where(VerificationCheck.employee_id == employee.id)
        .order_by(VerificationCheck.created_at.desc())
    ).all()
    return [VerificationCheckRead.model_validate(row) for row in rows]


@router.get(
    "/employees/{employee_id}/face-matches",
    response_model=list[FaceMatchRead],
    summary="Face-match history for an employee",
)
def list_face_matches(
    employee_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[FaceMatchRead]:
    employee = _get_employee_or_404(db, employee_id)
    _assert_can_view(employee, user)

    rows = db.scalars(
        select(FaceMatch)
        .where(FaceMatch.employee_id == employee.id)
        .order_by(FaceMatch.created_at.desc())
    ).all()
    return [FaceMatchRead.model_validate(row) for row in rows]


@router.get(
    "/employees/{employee_id}/verification-summary",
    response_model=VerificationSummary,
    summary="Consolidated verification state for the HR review screen",
)
def verification_summary(
    employee_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> VerificationSummary:
    employee = _get_employee_or_404(db, employee_id)
    _assert_can_view(employee, user)

    # A document approved elsewhere may already close a checklist item.
    if sync_document_checklist(db, employee=employee, actor=None):
        db.commit()

    documents = db.scalars(
        select(Document).where(Document.employee_id == employee.id)
    ).all()

    # Latest check per type — earlier attempts stay in history but do not gate.
    latest_checks: dict[str, VerificationCheck] = {}
    for check in db.scalars(
        select(VerificationCheck)
        .where(VerificationCheck.employee_id == employee.id)
        .order_by(VerificationCheck.created_at.desc())
    ).all():
        latest_checks.setdefault(check.check_type.value, check)

    face_match = db.scalar(
        select(FaceMatch)
        .where(FaceMatch.employee_id == employee.id)
        .order_by(FaceMatch.created_at.desc())
    )

    approved = [d for d in documents if d.status is DocumentStatus.APPROVED]
    rejected = [d for d in documents if d.status is DocumentStatus.REJECTED]
    pending = [
        d for d in documents
        if d.status in (DocumentStatus.UPLOADED, DocumentStatus.PROCESSING,
                        DocumentStatus.EXTRACTED, DocumentStatus.FAILED)
    ]

    approved_types = {d.document_type for d in approved}
    missing = sorted(t.value for t in REQUIRED_DOCUMENT_TYPES - approved_types)

    blocking: list[str] = []
    for name in missing:
        blocking.append(f"{name} has not been approved yet")
    for check in latest_checks.values():
        if check.status is not VerificationStatus.PASSED:
            blocking.append(
                f"{check.check_type.value} verification did not pass ({check.reason_code})"
            )
    if face_match is not None and face_match.status is not FaceMatchStatus.MATCHED:
        blocking.append(f"face match did not pass ({face_match.status.value})")
    elif face_match is None:
        blocking.append("face match has not been run")

    # Outstanding mandatory tasks also block completion (Phase 4).
    progress = compute_progress(db, employee.id)
    if progress.mandatory_outstanding:
        blocking.append(
            f"{progress.mandatory_outstanding} mandatory task(s) still outstanding"
        )

    return VerificationSummary(
        employee_id=employee.id,
        onboarding_status=employee.onboarding_status,
        id_checks=[VerificationCheckRead.model_validate(c) for c in latest_checks.values()],
        face_match=FaceMatchRead.model_validate(face_match) if face_match else None,
        documents_total=len(documents),
        documents_approved=len(approved),
        documents_rejected=len(rejected),
        documents_pending_review=len(pending),
        missing_document_types=missing,
        tasks_total=progress.total,
        tasks_completed=progress.completed + progress.waived,
        tasks_mandatory_outstanding=progress.mandatory_outstanding,
        tasks_overdue=progress.overdue,
        ready_for_completion=not blocking,
        blocking_issues=blocking,
    )


# --- HR decisions ----------------------------------------------------------


def _decide(
    db: DbSession,
    request: Request,
    actor: User,
    document: Document,
    *,
    new_status: DocumentStatus,
    reason: str | None,
    action: AuditAction,
) -> DocumentReviewResult:
    if document.status in (DocumentStatus.UPLOADED, DocumentStatus.PROCESSING):
        raise ConflictError(
            "Extraction is still running for this document. Review it once it completes."
        )

    document.status = new_status
    document.reviewed_by_id = actor.id
    document.reviewed_at = utcnow()
    document.rejection_reason = reason

    record_audit(
        db,
        action=action,
        actor=actor,
        entity_type="document",
        entity_id=document.id,
        detail={
            "employee_id": str(document.employee_id),
            "document_type": document.document_type.value,
            "reason": reason,
        },
        request=request,
    )

    notify_document_decision(db, document=document, actor=actor)
    onboarding_status = recalculate_onboarding_status(db, document.employee, actor=actor)
    db.commit()
    db.refresh(document)

    return DocumentReviewResult(
        document_id=document.id,
        status=document.status,
        reviewed_at=document.reviewed_at,
        rejection_reason=document.rejection_reason,
        onboarding_status=onboarding_status,
        message=(
            "Document approved."
            if new_status is DocumentStatus.APPROVED
            else "Document rejected. The employee can upload a replacement."
        ),
    )


@router.post(
    "/documents/{document_id}/approve",
    response_model=DocumentReviewResult,
    summary="Approve a document (HR)",
)
def approve_document(
    document_id: uuid.UUID,
    payload: DocumentReviewRequest,
    request: Request,
    db: DbSession,
    actor: HrUser,
) -> DocumentReviewResult:
    document = _get_document_or_404(db, document_id)
    return _decide(
        db,
        request,
        actor,
        document,
        new_status=DocumentStatus.APPROVED,
        reason=payload.note,
        action=AuditAction.DOCUMENT_APPROVED,
    )


@router.post(
    "/documents/{document_id}/reject",
    response_model=DocumentReviewResult,
    summary="Reject a document with a mandatory reason (HR)",
)
def reject_document(
    document_id: uuid.UUID,
    payload: DocumentRejectRequest,
    request: Request,
    db: DbSession,
    actor: HrUser,
) -> DocumentReviewResult:
    document = _get_document_or_404(db, document_id)
    return _decide(
        db,
        request,
        actor,
        document,
        new_status=DocumentStatus.REJECTED,
        reason=payload.reason,
        action=AuditAction.DOCUMENT_REJECTED,
    )


@router.post(
    "/employees/{employee_id}/complete-onboarding",
    response_model=DocumentReviewResult,
    summary="Mark onboarding complete once every check has passed (HR)",
)
def complete_onboarding(
    employee_id: uuid.UUID, request: Request, db: DbSession, actor: HrUser
) -> DocumentReviewResult:
    employee = _get_employee_or_404(db, employee_id)

    summary = verification_summary(employee_id, db, actor)
    if not summary.ready_for_completion:
        raise ConflictError(
            "Onboarding cannot be completed yet: " + "; ".join(summary.blocking_issues)
        )

    previous = employee.onboarding_status
    employee.onboarding_status = OnboardingStatus.COMPLETE
    employee.onboarding_completed_at = utcnow()

    record_audit(
        db,
        action=AuditAction.ONBOARDING_STATUS_CHANGED,
        actor=actor,
        entity_type="employee",
        entity_id=employee.id,
        detail={"from": previous.value, "to": OnboardingStatus.COMPLETE.value,
                "reason": "manually completed by HR"},
        request=request,
    )
    notify_onboarding_complete(db, employee=employee, actor=actor)
    db.commit()

    return DocumentReviewResult(
        document_id=employee.id,
        status=DocumentStatus.APPROVED,
        reviewed_at=employee.onboarding_completed_at,
        onboarding_status=OnboardingStatus.COMPLETE,
        message="Onboarding marked complete.",
    )
