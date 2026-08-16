"""Verification orchestration and onboarding status transitions (PRD A.6 steps 5-7).

Keeping the status rules here means the API layer never hand-rolls a transition,
so the employee's stage always reflects the actual state of their documents.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import utcnow
from app.models.document import Document, ExtractedField
from app.models.employee import Employee
from app.models.enums import (
    AuditAction,
    DocumentStatus,
    DocumentType,
    FaceMatchStatus,
    OnboardingStatus,
    VerificationCheckType,
    VerificationStatus,
)
from app.models.user import User
from app.models.verification import FaceMatch, VerificationCheck
from app.services.audit import record_audit
from app.services.face import compare_faces
from app.services.notifications import notify_verification_failed
from app.services.storage import get_storage
from app.services.verification import (
    VerificationOutcome,
    check_name_against_profile,
    verify_id_number,
)

logger = logging.getLogger(__name__)

# Document types that carry a government ID number worth verifying.
VERIFIABLE_TYPES = {DocumentType.AADHAAR: "aadhaar_number", DocumentType.PAN: "pan_number"}

# Documents an employee must supply before HR review can conclude.
REQUIRED_DOCUMENT_TYPES = {DocumentType.AADHAAR, DocumentType.PAN, DocumentType.PHOTO}

# Stages that represent progress *into* review; earlier stages are advanced, but
# a completed or rejected onboarding is never silently rewound.
_TERMINAL_STATUSES = {OnboardingStatus.COMPLETE, OnboardingStatus.REJECTED}

_STAGE_ORDER = [
    OnboardingStatus.INVITED,
    OnboardingStatus.REGISTERED,
    OnboardingStatus.DOCUMENTS_PENDING,
    OnboardingStatus.DOCUMENTS_SUBMITTED,
    OnboardingStatus.UNDER_REVIEW,
    OnboardingStatus.TASKS_ASSIGNED,
    OnboardingStatus.COMPLETE,
]


def _field_value(document: Document, field_name: str) -> str | None:
    for field in document.fields:
        if field.field_name == field_name:
            return field.effective_value
    return None


# --- ID verification -------------------------------------------------------


def run_id_verification(
    db: Session,
    *,
    document: Document,
    actor: User | None = None,
) -> VerificationCheck | None:
    """Run the mock registry check for an Aadhaar/PAN document.

    Returns None when the document type carries no verifiable ID number.
    """
    field_name = VERIFIABLE_TYPES.get(document.document_type)
    if field_name is None:
        return None

    check_type = VerificationCheckType(document.document_type.value)
    number = _field_value(document, field_name)
    document_name = _field_value(document, "full_name")
    employee = document.employee

    result = verify_id_number(
        check_type.value, number, expected_name=document_name or employee.full_name
    )

    # An ID that verifies but names someone else is still a problem for HR.
    similarity, name_matches = check_name_against_profile(
        document_name, employee.full_name
    )
    status = VerificationStatus(result.outcome.value)
    message = result.message
    reason_code = result.reason.value

    if result.outcome is VerificationOutcome.PASSED and not name_matches:
        status = VerificationStatus.FAILED
        reason_code = "name_mismatch"
        message = (
            f"The ID verified, but the name on it ({document_name!r}) does not match "
            f"the employee profile ({employee.full_name!r})."
        )

    check = VerificationCheck(
        employee_id=employee.id,
        document_id=document.id,
        check_type=check_type,
        status=status,
        reason_code=reason_code,
        message=message,
        provider=result.provider,
        reference_id=result.reference_id,
        masked_number=result.masked_number,
        name_similarity=similarity,
        detail={**result.as_dict(), "profile_name": employee.full_name,
                "document_name": document_name, "name_matches": name_matches},
        performed_by_id=actor.id if actor else None,
    )
    db.add(check)
    db.flush()

    record_audit(
        db,
        action=AuditAction.ID_VERIFICATION_RUN,
        actor=actor,
        actor_email=None if actor else "system",
        entity_type="document",
        entity_id=document.id,
        detail={
            "check_type": check_type.value,
            "status": status.value,
            "reason": reason_code,
            "masked_number": result.masked_number,
            "provider": result.provider,
        },
    )

    if status is VerificationStatus.FAILED:
        notify_verification_failed(
            db,
            employee=employee,
            check_type=check_type.value,
            reason=reason_code,
            message=message,
        )
    return check


# --- Face matching ---------------------------------------------------------


def _latest_document(db: Session, employee_id, document_type: DocumentType) -> Document | None:
    return db.scalar(
        select(Document)
        .where(
            Document.employee_id == employee_id,
            Document.document_type == document_type,
            Document.status != DocumentStatus.REJECTED,
        )
        .order_by(Document.created_at.desc())
    )


def run_face_match(
    db: Session,
    *,
    employee: Employee,
    actor: User | None = None,
    id_document: Document | None = None,
) -> FaceMatch | None:
    """Compare the employee's photo against the photo on their ID document.

    Returns None when either side is missing — the caller reports that as
    "nothing to compare yet" rather than a failed match.
    """
    photo = _latest_document(db, employee.id, DocumentType.PHOTO)
    if photo is None:
        return None

    if id_document is None:
        id_document = _latest_document(
            db, employee.id, DocumentType.AADHAAR
        ) or _latest_document(db, employee.id, DocumentType.PAN)
    if id_document is None:
        return None

    storage = get_storage()
    try:
        photo_bytes = storage.load(photo.storage_key)
        id_bytes = storage.load(id_document.storage_key)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not load images for face matching")
        match = FaceMatch(
            employee_id=employee.id,
            photo_document_id=photo.id,
            id_document_id=id_document.id,
            status=FaceMatchStatus.ERROR,
            message=f"Could not read the stored images: {exc}"[:500],
            performed_by_id=actor.id if actor else None,
        )
        db.add(match)
        db.flush()
        return match

    # A PDF ID scan has to be rasterised before a face can be found in it.
    if id_document.content_type == "application/pdf":
        id_bytes = _pdf_first_page_png(id_bytes)

    result = compare_faces(photo_bytes, id_bytes)

    match = FaceMatch(
        employee_id=employee.id,
        photo_document_id=photo.id,
        id_document_id=id_document.id,
        status=FaceMatchStatus(result.outcome.value),
        similarity=result.similarity,
        threshold=result.threshold,
        engine=result.engine,
        message=result.message,
        detail=result.as_dict(),
        performed_by_id=actor.id if actor else None,
    )
    db.add(match)
    db.flush()

    record_audit(
        db,
        action=AuditAction.FACE_MATCH_RUN,
        actor=actor,
        actor_email=None if actor else "system",
        entity_type="employee",
        entity_id=employee.id,
        detail={
            "status": match.status.value,
            "similarity": result.similarity,
            "threshold": result.threshold,
            "engine": result.engine,
            "photo_document_id": str(photo.id),
            "id_document_id": str(id_document.id),
        },
    )
    return match


def _pdf_first_page_png(data: bytes) -> bytes:
    """Render page 1 of a PDF to PNG so the face detector can read it."""
    import fitz

    with fitz.open(stream=data, filetype="pdf") as pdf:
        if pdf.page_count == 0:
            return data
        zoom = settings.OCR_PDF_DPI / 72.0
        pixmap = pdf[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        return pixmap.tobytes("png")


# --- Onboarding status transitions -----------------------------------------


def _set_status(
    db: Session,
    employee: Employee,
    new_status: OnboardingStatus,
    *,
    actor: User | None = None,
    reason: str | None = None,
) -> bool:
    if employee.onboarding_status is new_status:
        return False

    previous = employee.onboarding_status
    employee.onboarding_status = new_status
    if new_status is OnboardingStatus.COMPLETE:
        employee.onboarding_completed_at = utcnow()

    record_audit(
        db,
        action=AuditAction.ONBOARDING_STATUS_CHANGED,
        actor=actor,
        actor_email=None if actor else "system",
        entity_type="employee",
        entity_id=employee.id,
        detail={"from": previous.value, "to": new_status.value, "reason": reason},
    )
    return True


def recalculate_onboarding_status(
    db: Session, employee: Employee, *, actor: User | None = None
) -> OnboardingStatus:
    """Derive the employee's stage from the current state of their documents."""
    if employee.onboarding_status in _TERMINAL_STATUSES:
        return employee.onboarding_status

    documents = db.scalars(
        select(Document).where(Document.employee_id == employee.id)
    ).all()

    if not documents:
        # Registered but nothing uploaded yet.
        if employee.user_id is not None and employee.onboarding_status in (
            OnboardingStatus.INVITED,
            OnboardingStatus.REGISTERED,
        ):
            _set_status(db, employee, OnboardingStatus.DOCUMENTS_PENDING,
                        actor=actor, reason="awaiting document upload")
        return employee.onboarding_status

    present_types = {d.document_type for d in documents if d.status != DocumentStatus.REJECTED}
    has_all_required = REQUIRED_DOCUMENT_TYPES <= present_types

    reviewed = [
        d for d in documents
        if d.status in (DocumentStatus.APPROVED, DocumentStatus.REJECTED)
    ]
    required_docs = [d for d in documents if d.document_type in REQUIRED_DOCUMENT_TYPES]
    all_required_approved = bool(required_docs) and has_all_required and all(
        d.status is DocumentStatus.APPROVED
        for d in required_docs
        if d.status != DocumentStatus.REJECTED
    ) and REQUIRED_DOCUMENT_TYPES <= {
        d.document_type for d in required_docs if d.status is DocumentStatus.APPROVED
    }

    if all_required_approved:
        # Reaching this stage is what triggers the rule engine (PRD A.6 step 7).
        from app.services.assignment import assign_tasks, sync_document_checklist

        assign_tasks(db, employee=employee, actor=actor)
        sync_document_checklist(db, employee=employee, actor=actor)

        target = OnboardingStatus.TASKS_ASSIGNED
        reason = "all required documents approved"
    elif reviewed or has_all_required:
        target = OnboardingStatus.UNDER_REVIEW
        reason = "documents awaiting or undergoing HR review"
    else:
        target = OnboardingStatus.DOCUMENTS_SUBMITTED
        reason = "some documents uploaded"

    # Only ever move forward through the pipeline.
    current_index = (
        _STAGE_ORDER.index(employee.onboarding_status)
        if employee.onboarding_status in _STAGE_ORDER
        else -1
    )
    if _STAGE_ORDER.index(target) > current_index:
        _set_status(db, employee, target, actor=actor, reason=reason)

    return employee.onboarding_status


# --- Background entry point ------------------------------------------------


def run_verification_for_document(document_id: uuid.UUID | str) -> None:
    """Post-extraction hook: verify the ID and refresh the employee's stage.

    Opens its own session so it can run as a background task or, later, a queue
    worker. Never raises.
    """
    db: Session = SessionLocal()
    try:
        document = db.get(Document, uuid.UUID(str(document_id)))
        if document is None or document.status is not DocumentStatus.EXTRACTED:
            return

        if document.document_type in VERIFIABLE_TYPES:
            run_id_verification(db, document=document, actor=None)

        # A new photo or ID makes any previous face match stale.
        if document.document_type in (
            DocumentType.PHOTO,
            DocumentType.AADHAAR,
            DocumentType.PAN,
        ):
            run_face_match(db, employee=document.employee, actor=None)

        recalculate_onboarding_status(db, document.employee, actor=None)
        db.commit()
    except Exception:  # noqa: BLE001 - must never kill the worker
        db.rollback()
        logger.exception("Verification failed for document %s", document_id)
    finally:
        db.close()
