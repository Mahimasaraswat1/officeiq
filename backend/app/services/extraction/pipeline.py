"""Document processing pipeline: fetch -> OCR -> extract -> persist.

Runs in a background task today (PRD B.9.4 calls for a queue/worker split in
Phase 8). `process_document` opens its own session so it is already safe to move
behind Celery/RQ: the only change is how it gets invoked.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import utcnow
from app.models.document import Document, ExtractedField, ResumeProfile
from app.models.enums import (
    AuditAction,
    DocumentStatus,
    DocumentType,
    ExtractionSource,
)
from app.services.audit import record_audit
from app.services.extraction.fields import extract_fields
from app.services.extraction.resume import parse_resume
from app.services.ocr import extract_text
from app.services.storage import get_storage

logger = logging.getLogger(__name__)


def _source_for(engine_name: str) -> ExtractionSource:
    if engine_name == "pdf_text":
        return ExtractionSource.PDF_TEXT
    return ExtractionSource.OCR


def process_document(document_id: uuid.UUID | str) -> None:
    """Extract data from one stored document and persist the results.

    Never raises: failures are recorded on the document so HR sees a clear
    status instead of a silently stuck row.
    """
    db: Session = SessionLocal()
    try:
        document = db.get(Document, uuid.UUID(str(document_id)))
        if document is None:
            logger.warning("process_document: %s no longer exists", document_id)
            return

        document.status = DocumentStatus.PROCESSING
        document.error_message = None
        db.commit()

        try:
            data = get_storage().load(document.storage_key)
            result = extract_text(data, document.content_type)

            document.raw_text = (result.text or "")[:100_000] or None
            document.ocr_confidence = result.mean_confidence
            document.extraction_source = _source_for(result.engine)

            # Replace previous results so reprocessing is idempotent.
            db.query(ExtractedField).filter(
                ExtractedField.document_id == document.id
            ).delete(synchronize_session=False)

            if document.document_type is DocumentType.RESUME:
                _persist_resume(db, document, result)
            else:
                _persist_fields(db, document, result)

            document.status = DocumentStatus.EXTRACTED
            document.processed_at = utcnow()

            record_audit(
                db,
                action=AuditAction.DOCUMENT_EXTRACTED,
                actor=None,
                actor_email="system",
                entity_type="document",
                entity_id=document.id,
                detail={
                    "document_type": document.document_type.value,
                    "engine": result.engine,
                    "mean_confidence": document.ocr_confidence,
                    "fields_found": len(document.fields),
                },
            )
            db.commit()
            logger.info(
                "Extracted %s (%s): %d field(s), confidence %.2f",
                document.id,
                document.document_type.value,
                len(document.fields),
                document.ocr_confidence or 0.0,
            )

        except Exception as exc:  # noqa: BLE001 - must never kill the worker
            db.rollback()
            logger.exception("Extraction failed for document %s", document_id)
            document = db.get(Document, uuid.UUID(str(document_id)))
            if document is not None:
                document.status = DocumentStatus.FAILED
                document.error_message = str(exc)[:1000]
                document.processed_at = utcnow()
                record_audit(
                    db,
                    action=AuditAction.DOCUMENT_EXTRACTION_FAILED,
                    actor=None,
                    actor_email="system",
                    entity_type="document",
                    entity_id=document.id,
                    detail={"error": str(exc)[:500]},
                )
                db.commit()
    finally:
        db.close()


def _persist_fields(db: Session, document: Document, result) -> None:
    for candidate in extract_fields(document.document_type.value, result):
        db.add(
            ExtractedField(
                document_id=document.id,
                field_name=candidate.field_name,
                value=candidate.value,
                confidence=candidate.confidence,
                source=_source_for(result.engine),
            )
        )
    db.flush()


def _persist_resume(db: Session, document: Document, result) -> None:
    parsed = parse_resume(result)

    existing = db.scalar(
        select(ResumeProfile).where(ResumeProfile.document_id == document.id)
    )
    if existing is not None:
        db.delete(existing)
        db.flush()

    db.add(
        ResumeProfile(
            document_id=document.id,
            employee_id=document.employee_id,
            candidate_name=parsed.candidate_name,
            email=parsed.email,
            phone=parsed.phone,
            total_experience_years=parsed.total_experience_years,
            education=parsed.education,
            experience=parsed.experience,
            skills=parsed.skills,
            confidence=parsed.confidence,
        )
    )

    # Surface the directly usable resume values as fields too, so the
    # "apply to profile" flow treats every document type the same way.
    simple = {
        "full_name": parsed.candidate_name,
        "email": parsed.email,
        "phone": parsed.phone,
    }
    for name, value in simple.items():
        if value:
            db.add(
                ExtractedField(
                    document_id=document.id,
                    field_name=name,
                    value=str(value)[:512],
                    confidence=parsed.confidence,
                    source=ExtractionSource.RESUME_PARSER,
                )
            )
    db.flush()
