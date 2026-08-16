"""Document upload, extraction review, and download (PRD A.7.3 / B.4.3)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, HrUser
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.security import utcnow
from app.models.document import Document, ExtractedField
from app.models.employee import Employee
from app.models.enums import AuditAction, DocumentStatus, DocumentType, UserRole
from app.models.user import User
from app.schemas.common import Message
from app.schemas.document import (
    ApplyExtractionRequest,
    ApplyExtractionResponse,
    DocumentDetail,
    DocumentRead,
    DownloadLink,
    ExtractedFieldOut,
    FieldCorrection,
    ResumeProfileRead,
)
from app.services.audit import record_audit
from app.services.extraction.fields import parse_date
from app.services.notifications import notify_document_uploaded
from app.services.extraction.pipeline import process_document
from app.services.review import recalculate_onboarding_status, run_verification_for_document
from app.services.storage import (
    StorageError,
    build_object_key,
    get_storage,
    issue_download_token,
    verify_download_token,
)
from app.services.upload_validation import safe_display_filename, validate_upload

router = APIRouter(tags=["Documents"])

RAW_TEXT_PREVIEW_CHARS = 2000

# Extracted field -> Employee column. Fields absent here (aadhaar_number,
# pan_number, father_name, gender) are verification inputs for Phase 3, not
# profile columns, so they are never auto-applied.
FIELD_TO_EMPLOYEE_COLUMN = {
    "date_of_birth": "date_of_birth",
    "phone": "phone",
    "email": "personal_email",
    "postal_code": "postal_code",
    "address_line1": "address_line1",
    "city": "city",
    "state": "state",
}


# --- Access control --------------------------------------------------------


def _get_employee_or_404(db: DbSession, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Employee not found.")
    return employee


def _assert_can_access_employee(employee: Employee, user: User) -> None:
    """HR/Admin reach any employee; an employee only their own record."""
    if user.role in (UserRole.ADMIN, UserRole.HR):
        return
    if employee.user_id != user.id:
        raise PermissionDeniedError("You can only access your own documents.")


def _get_document_or_404(db: DbSession, document_id: uuid.UUID) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Document not found.")
    return document


def _detail(document: Document) -> DocumentDetail:
    preview = (document.raw_text or "")[:RAW_TEXT_PREVIEW_CHARS] or None
    return DocumentDetail(
        **DocumentRead.model_validate(document).model_dump(),
        fields=[ExtractedFieldOut.from_model(f) for f in document.fields],
        resume_profile=(
            ResumeProfileRead.model_validate(document.resume_profile)
            if document.resume_profile
            else None
        ),
        raw_text_preview=preview,
    )


def _schedule_processing(background: BackgroundTasks, document_id: uuid.UUID) -> None:
    """Queue extraction, then verification.

    BackgroundTasks run in order, so verification always sees the extracted
    fields. Both run inline in tests so assertions are deterministic.
    """
    if settings.OCR_PROCESS_SYNCHRONOUSLY:
        process_document(document_id)
    else:
        background.add_task(process_document, document_id)

    if settings.VERIFICATION_PROCESS_SYNCHRONOUSLY:
        run_verification_for_document(document_id)
    else:
        background.add_task(run_verification_for_document, document_id)


# --- Upload & list ---------------------------------------------------------


@router.post(
    "/employees/{employee_id}/documents",
    response_model=DocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document and start extraction",
)
async def upload_document(
    employee_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
    document_type: Annotated[DocumentType, Form()],
    file: Annotated[UploadFile, File()],
) -> DocumentRead:
    employee = _get_employee_or_404(db, employee_id)
    _assert_can_access_employee(employee, user)

    data = await file.read()
    validated = validate_upload(
        data=data,
        filename=file.filename or "",
        document_type=document_type.value,
        declared_type=file.content_type,
    )
    display_name = safe_display_filename(file.filename or "upload")

    key = build_object_key(employee.id, document_type.value, display_name)
    try:
        stored = get_storage().save(key, data, validated.content_type)
    except StorageError as exc:
        raise ValidationError(f"Could not store the file: {exc}") from exc

    document = Document(
        employee_id=employee.id,
        document_type=document_type,
        original_filename=display_name,
        storage_key=stored.key,
        content_type=validated.content_type,
        size_bytes=stored.size_bytes,
        checksum_sha256=stored.checksum_sha256,
        status=DocumentStatus.UPLOADED,
        uploaded_by_id=user.id,
    )
    db.add(document)
    db.flush()

    record_audit(
        db,
        action=AuditAction.DOCUMENT_UPLOADED,
        actor=user,
        entity_type="document",
        entity_id=document.id,
        detail={
            "employee_id": str(employee.id),
            "document_type": document_type.value,
            "filename": display_name,
            "size_bytes": stored.size_bytes,
        },
        request=request,
    )
    notify_document_uploaded(db, document=document, actor=user)
    db.commit()
    db.refresh(document)

    _schedule_processing(background, document.id)
    db.refresh(document)
    return DocumentRead.model_validate(document)


@router.get(
    "/employees/{employee_id}/documents",
    response_model=list[DocumentRead],
    summary="List an employee's documents",
)
def list_documents(
    employee_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    document_type: DocumentType | None = None,
) -> list[DocumentRead]:
    employee = _get_employee_or_404(db, employee_id)
    _assert_can_access_employee(employee, user)

    filters = [Document.employee_id == employee.id]
    if document_type:
        filters.append(Document.document_type == document_type)

    rows = db.scalars(
        select(Document).where(*filters).order_by(Document.created_at.desc())
    ).all()
    return [DocumentRead.model_validate(row) for row in rows]


# --- Single document -------------------------------------------------------


@router.get(
    "/documents/{document_id}",
    response_model=DocumentDetail,
    summary="Get a document with its extraction results",
)
def get_document(
    document_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> DocumentDetail:
    document = _get_document_or_404(db, document_id)
    _assert_can_access_employee(document.employee, user)
    return _detail(document)


@router.post(
    "/documents/{document_id}/reprocess",
    response_model=DocumentDetail,
    summary="Re-run extraction on a document",
)
def reprocess_document(
    document_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    actor: HrUser,
) -> DocumentDetail:
    document = _get_document_or_404(db, document_id)
    if document.status is DocumentStatus.PROCESSING:
        raise ConflictError("This document is already being processed.")

    record_audit(
        db,
        action=AuditAction.DOCUMENT_REPROCESSED,
        actor=actor,
        entity_type="document",
        entity_id=document.id,
        request=request,
    )
    db.commit()

    _schedule_processing(background, document.id)
    db.refresh(document)
    return _detail(document)


@router.delete(
    "/documents/{document_id}", response_model=Message, summary="Delete a document"
)
def delete_document(
    document_id: uuid.UUID, request: Request, db: DbSession, user: CurrentUser
) -> Message:
    document = _get_document_or_404(db, document_id)
    _assert_can_access_employee(document.employee, user)

    # Once HR has ruled on a document, only HR/Admin may remove it.
    if document.status in (DocumentStatus.APPROVED, DocumentStatus.REJECTED) and (
        user.role not in (UserRole.ADMIN, UserRole.HR)
    ):
        raise PermissionDeniedError("This document has been reviewed and cannot be deleted.")

    storage_key = document.storage_key
    record_audit(
        db,
        action=AuditAction.DOCUMENT_DELETED,
        actor=user,
        entity_type="document",
        entity_id=document.id,
        detail={
            "employee_id": str(document.employee_id),
            "document_type": document.document_type.value,
            "filename": document.original_filename,
        },
        request=request,
    )
    db.delete(document)
    db.commit()

    # Remove the blob only after the row is gone, so a storage error can never
    # leave a database row pointing at a deleted object.
    try:
        get_storage().delete(storage_key)
    except StorageError:
        # Orphaned blobs are harmless and reclaimable; the record is what matters.
        pass

    return Message(message="Document deleted.")


# --- Download --------------------------------------------------------------


@router.get(
    "/documents/{document_id}/download-url",
    response_model=DownloadLink,
    summary="Get a time-limited download link",
)
def get_download_url(
    document_id: uuid.UUID, request: Request, db: DbSession, user: CurrentUser
) -> DownloadLink:
    document = _get_document_or_404(db, document_id)
    _assert_can_access_employee(document.employee, user)

    expires_in = settings.DOWNLOAD_URL_EXPIRE_SECONDS

    record_audit(
        db,
        action=AuditAction.DOCUMENT_DOWNLOADED,
        actor=user,
        entity_type="document",
        entity_id=document.id,
        request=request,
    )
    db.commit()

    # S3 can serve the object directly; otherwise proxy through this API.
    direct = get_storage().signed_url(document.storage_key, expires_in)
    if direct:
        return DownloadLink(url=direct, expires_in_seconds=expires_in)

    token = issue_download_token(document.id, expires_in)
    path = f"{settings.API_V1_PREFIX}/documents/{document.id}/download?token={token}"
    return DownloadLink(url=path, expires_in_seconds=expires_in)


@router.get(
    "/documents/{document_id}/download",
    summary="Download a document using a signed token",
    response_class=Response,
)
def download_document(
    document_id: uuid.UUID,
    db: DbSession,
    token: Annotated[str, Query(description="Signed token from /download-url")],
) -> Response:
    # Authorised by the signed token alone, so <img>/<iframe> tags can load it
    # without an Authorization header. The token is short-lived and per-document.
    verified_id = verify_download_token(token)
    if verified_id is None or verified_id != str(document_id):
        raise PermissionDeniedError("This download link is invalid or has expired.")

    document = _get_document_or_404(db, document_id)
    try:
        data = get_storage().load(document.storage_key)
    except StorageError as exc:
        raise NotFoundError("The stored file could not be found.") from exc

    return Response(
        content=data,
        media_type=document.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{document.original_filename}"',
            "Cache-Control": "private, no-store",
        },
    )


# --- Extraction review -----------------------------------------------------


@router.patch(
    "/documents/{document_id}/fields/{field_id}",
    response_model=ExtractedFieldOut,
    summary="Correct an extracted field",
)
def correct_field(
    document_id: uuid.UUID,
    field_id: uuid.UUID,
    payload: FieldCorrection,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ExtractedFieldOut:
    document = _get_document_or_404(db, document_id)
    _assert_can_access_employee(document.employee, user)

    field = db.get(ExtractedField, field_id)
    if field is None or field.document_id != document.id:
        raise NotFoundError("Extracted field not found on this document.")

    field.corrected_value = payload.corrected_value
    field.corrected_by_id = user.id
    field.corrected_at = utcnow()

    record_audit(
        db,
        action=AuditAction.DOCUMENT_EXTRACTED,
        actor=user,
        entity_type="extracted_field",
        entity_id=field.id,
        detail={
            "document_id": str(document.id),
            "field_name": field.field_name,
            "original": field.value,
            "corrected": payload.corrected_value,
        },
        request=request,
    )
    db.commit()
    db.refresh(field)
    return ExtractedFieldOut.from_model(field)


@router.post(
    "/documents/{document_id}/apply-to-profile",
    response_model=ApplyExtractionResponse,
    summary="Copy extracted values onto the employee profile",
)
def apply_extraction(
    document_id: uuid.UUID,
    payload: ApplyExtractionRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> ApplyExtractionResponse:
    document = _get_document_or_404(db, document_id)
    employee = document.employee
    _assert_can_access_employee(employee, user)

    if document.status is not DocumentStatus.EXTRACTED:
        raise ConflictError(
            f"Extraction has not completed for this document (status: {document.status.value})."
        )

    applied: dict[str, str] = {}
    skipped: dict[str, str] = {}

    for field in document.fields:
        name = field.field_name
        if payload.field_names is not None and name not in payload.field_names:
            continue

        column = FIELD_TO_EMPLOYEE_COLUMN.get(name)
        if column is None:
            skipped[name] = "not a profile field"
            continue

        value = field.effective_value
        if not value:
            skipped[name] = "no value extracted"
            continue

        # A manual correction is trusted regardless of the original OCR score.
        is_corrected = field.corrected_value is not None
        if not is_corrected and field.confidence < payload.min_confidence:
            skipped[name] = f"confidence {field.confidence:.2f} below threshold"
            continue

        if column == "date_of_birth":
            parsed = parse_date(value)
            if parsed is None:
                skipped[name] = "unparseable date"
                continue
            setattr(employee, column, parsed)
            applied[name] = parsed.isoformat()
        else:
            setattr(employee, column, value[:255])
            applied[name] = value

    if applied:
        record_audit(
            db,
            action=AuditAction.EXTRACTION_APPLIED,
            actor=user,
            entity_type="employee",
            entity_id=employee.id,
            detail={"document_id": str(document.id), "applied": applied},
            request=request,
        )
        db.commit()

    return ApplyExtractionResponse(
        applied=applied,
        skipped=skipped,
        message=(
            f"Applied {len(applied)} field(s) to the employee profile."
            if applied
            else "No fields were applied."
        ),
    )
