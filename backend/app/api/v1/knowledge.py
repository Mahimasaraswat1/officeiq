"""Knowledge base administration (HR) — PRD A.7.6 / B.4.6 ingestion pipeline."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Request, status
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, HrUser
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError
from app.models.enums import (
    AuditAction,
    KnowledgeCategory,
    KnowledgeStatus,
    UserRole,
)
from app.models.knowledge import KnowledgeDocument
from app.schemas.common import Message
from app.schemas.knowledge import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentDetail,
    KnowledgeDocumentRead,
    KnowledgeDocumentUpdate,
    KnowledgeStats,
    RetrievalPreviewRequest,
    RetrievalPreviewResponse,
    RetrievedChunkRead,
)
from app.services.audit import record_audit
from app.services.embeddings import get_embedder
from app.services.knowledge import ingest_document, knowledge_base_stats
from app.services.retrieval import retrieve

router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])

# Editing any of these changes what gets embedded, so the document must be
# re-ingested for the change to affect retrieval.
REINGEST_FIELDS = {"content", "title", "category"}


def _schedule_ingest(background: BackgroundTasks, document_id: uuid.UUID) -> None:
    """Queue ingestion. Runs inline in tests so assertions are deterministic."""
    if settings.INGEST_PROCESS_SYNCHRONOUSLY:
        ingest_document(document_id)
    else:
        background.add_task(ingest_document, document_id)


@router.get("/stats", response_model=KnowledgeStats, summary="Knowledge base overview")
def stats(db: DbSession, _: HrUser) -> KnowledgeStats:
    embedder = get_embedder()
    return KnowledgeStats(
        **knowledge_base_stats(db),
        embedding_provider=embedder.name,
        chat_provider=settings.CHAT_PROVIDER,
        chat_model=settings.CHAT_MODEL,
    )


@router.get(
    "/documents",
    response_model=list[KnowledgeDocumentRead],
    summary="List knowledge documents",
)
def list_documents(
    db: DbSession,
    _: HrUser,
    category: KnowledgeCategory | None = None,
    doc_status: KnowledgeStatus | None = None,
) -> list[KnowledgeDocumentRead]:
    filters = []
    if category:
        filters.append(KnowledgeDocument.category == category)
    if doc_status:
        filters.append(KnowledgeDocument.status == doc_status)

    rows = db.scalars(
        select(KnowledgeDocument)
        .where(*filters)
        .order_by(KnowledgeDocument.created_at.desc())
    ).all()
    return [KnowledgeDocumentRead.model_validate(row) for row in rows]


@router.post(
    "/documents",
    response_model=KnowledgeDocumentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a document and ingest it into the vector store",
)
def create_document(
    payload: KnowledgeDocumentCreate,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    actor: HrUser,
) -> KnowledgeDocumentRead:
    document = KnowledgeDocument(
        **payload.model_dump(),
        status=KnowledgeStatus.PENDING,
        created_by_id=actor.id,
    )
    db.add(document)
    db.flush()

    record_audit(
        db,
        action=AuditAction.KNOWLEDGE_DOC_CREATED,
        actor=actor,
        entity_type="knowledge_document",
        entity_id=document.id,
        detail={"title": document.title, "category": document.category.value},
        request=request,
    )
    db.commit()
    db.refresh(document)

    _schedule_ingest(background, document.id)
    db.refresh(document)
    return KnowledgeDocumentRead.model_validate(document)


@router.get(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentDetail,
    summary="Get a document with its full text",
)
def get_document(
    document_id: uuid.UUID, db: DbSession, _: HrUser
) -> KnowledgeDocumentDetail:
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise NotFoundError("Knowledge document not found.")
    return KnowledgeDocumentDetail.model_validate(document)


@router.patch(
    "/documents/{document_id}",
    response_model=KnowledgeDocumentRead,
    summary="Update a document (re-ingests when the text changes)",
)
def update_document(
    document_id: uuid.UUID,
    payload: KnowledgeDocumentUpdate,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    actor: HrUser,
) -> KnowledgeDocumentRead:
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise NotFoundError("Knowledge document not found.")

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(document, field, value)

    needs_reingest = bool(REINGEST_FIELDS & changes.keys())
    if needs_reingest:
        # Mark stale immediately so it stops being served with old embeddings.
        document.status = KnowledgeStatus.PENDING

    record_audit(
        db,
        action=AuditAction.KNOWLEDGE_DOC_UPDATED,
        actor=actor,
        entity_type="knowledge_document",
        entity_id=document.id,
        detail={"fields": sorted(changes.keys()), "reingested": needs_reingest},
        request=request,
    )
    db.commit()
    db.refresh(document)

    if needs_reingest:
        _schedule_ingest(background, document.id)
        db.refresh(document)

    return KnowledgeDocumentRead.model_validate(document)


@router.post(
    "/documents/{document_id}/reingest",
    response_model=KnowledgeDocumentRead,
    summary="Re-chunk and re-embed a document",
)
def reingest(
    document_id: uuid.UUID,
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    actor: HrUser,
) -> KnowledgeDocumentRead:
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise NotFoundError("Knowledge document not found.")
    if document.status is KnowledgeStatus.INGESTING:
        raise ConflictError("This document is already being ingested.")

    _schedule_ingest(background, document.id)
    db.refresh(document)
    return KnowledgeDocumentRead.model_validate(document)


@router.delete(
    "/documents/{document_id}", response_model=Message, summary="Delete a document"
)
def delete_document(
    document_id: uuid.UUID, request: Request, db: DbSession, actor: CurrentUser
) -> Message:
    if actor.role not in (UserRole.ADMIN, UserRole.HR):
        raise PermissionDeniedError("Only HR or an administrator can delete documents.")

    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise NotFoundError("Knowledge document not found.")

    record_audit(
        db,
        action=AuditAction.KNOWLEDGE_DOC_DELETED,
        actor=actor,
        entity_type="knowledge_document",
        entity_id=document.id,
        detail={"title": document.title, "chunks": document.chunk_count},
        request=request,
    )
    db.delete(document)
    db.commit()
    return Message(message="Knowledge document and its chunks deleted.")


@router.post(
    "/search",
    response_model=RetrievalPreviewResponse,
    summary="Preview what retrieval returns for a query (HR tooling)",
)
def search_preview(
    payload: RetrievalPreviewRequest, db: DbSession, _: HrUser
) -> RetrievalPreviewResponse:
    """Lets HR see exactly which passages a question would surface.

    Useful for diagnosing a bad answer without going through the chatbot.
    """
    chunks = retrieve(
        db, payload.query, top_k=payload.top_k, category=payload.category
    )
    return RetrievalPreviewResponse(
        query=payload.query,
        results=[
            RetrievedChunkRead(
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_title=c.document_title,
                source_reference=c.source_reference,
                heading=c.heading,
                category=c.category,
                chunk_index=c.chunk_index,
                similarity=round(c.similarity, 4),
                content=c.content,
            )
            for c in chunks
        ],
        total=len(chunks),
    )
