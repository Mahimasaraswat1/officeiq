"""Chunking and ingestion of knowledge base documents (PRD B.4.6).

Chunking is heading-aware: policy documents are structured, and splitting on
section boundaries keeps each chunk about one topic. That makes retrieval hits
more precise and lets an answer cite the section it came from rather than a
character range.
"""

from __future__ import annotations

import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import utcnow
from app.models.enums import AuditAction, KnowledgeStatus
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.services.audit import record_audit
from app.services.embeddings import get_embedder

logger = logging.getLogger(__name__)

# Markdown ATX headings and common "1. TITLE" / "SECTION:" policy headings.
HEADING_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s+(?P<md>.+)"
    r"|(?P<numbered>\d+(?:\.\d+)*\.?\s+[A-Z][^\n]{2,80})"
    r"|(?P<caps>[A-Z][A-Z0-9 ,&/()-]{4,80}):?)\s*$",
    re.MULTILINE,
)

# Rough average across English prose; used only for display and budgeting.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _split_sections(text: str) -> list[tuple[str | None, str]]:
    """Split into (heading, body) pairs, preserving pre-heading preamble."""
    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return [(None, text)]

    sections: list[tuple[str | None, str]] = []

    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append((None, preamble))

    for index, match in enumerate(matches):
        heading = (
            match.group("md") or match.group("numbered") or match.group("caps") or ""
        ).strip().rstrip(":")
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end].strip()
        if body:
            sections.append((heading[:255], body))
        elif heading:
            # A heading with no body still carries meaning as a label.
            sections.append((heading[:255], heading))

    return sections


def _split_long_text(text: str, target: int, overlap: int) -> list[str]:
    """Split a long section on paragraph, then sentence, boundaries."""
    if len(text) <= target:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    current = ""

    for paragraph in paragraphs:
        # A single paragraph over target gets broken at sentence boundaries.
        if len(paragraph) > target:
            if current:
                pieces.append(current)
                current = ""
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            buffer = ""
            for sentence in sentences:
                if buffer and len(buffer) + len(sentence) + 1 > target:
                    pieces.append(buffer.strip())
                    # Carry a tail of the previous piece so a fact split across
                    # the boundary is still retrievable from either side.
                    buffer = (buffer[-overlap:] + " " + sentence) if overlap else sentence
                else:
                    buffer = f"{buffer} {sentence}".strip()
            if buffer.strip():
                pieces.append(buffer.strip())
            continue

        if current and len(current) + len(paragraph) + 2 > target:
            pieces.append(current)
            current = (current[-overlap:] + "\n\n" + paragraph) if overlap else paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip()

    if current.strip():
        pieces.append(current.strip())

    return [p for p in pieces if p.strip()]


def chunk_document(
    content: str,
    *,
    target_chars: int | None = None,
    overlap_chars: int | None = None,
) -> list[tuple[str | None, str]]:
    """Split source text into (heading, chunk_text) pairs."""
    target = target_chars if target_chars is not None else settings.CHUNK_TARGET_CHARS
    overlap = overlap_chars if overlap_chars is not None else settings.CHUNK_OVERLAP_CHARS

    chunks: list[tuple[str | None, str]] = []
    for heading, body in _split_sections(content):
        for piece in _split_long_text(body, target, overlap):
            # Prefixing the heading gives the embedder topical context that the
            # body alone may not carry (e.g. a bare "20 days per year").
            text = f"{heading}\n\n{piece}" if heading else piece
            chunks.append((heading, text.strip()))

    return [c for c in chunks if c[1]]


# --- Ingestion -------------------------------------------------------------


def ingest_document(document_id: uuid.UUID | str) -> None:
    """Chunk, embed, and store one document. Never raises.

    Opens its own session so it can run as a background task or, later, a queue
    worker (PRD B.9.4).
    """
    db: Session = SessionLocal()
    try:
        document = db.get(KnowledgeDocument, uuid.UUID(str(document_id)))
        if document is None:
            logger.warning("ingest_document: %s no longer exists", document_id)
            return

        document.status = KnowledgeStatus.INGESTING
        document.error_message = None
        db.commit()

        try:
            # Re-ingestion replaces prior chunks, so it is idempotent.
            db.query(KnowledgeChunk).filter(
                KnowledgeChunk.document_id == document.id
            ).delete(synchronize_session=False)
            db.flush()

            pieces = chunk_document(document.content)
            if not pieces:
                raise ValueError("Document produced no chunks — is the content empty?")

            embedder = get_embedder()
            vectors = embedder.embed_documents([text for _, text in pieces])
            if len(vectors) != len(pieces):
                raise ValueError(
                    f"Embedder returned {len(vectors)} vectors for {len(pieces)} chunks"
                )

            for index, ((heading, text), vector) in enumerate(
                zip(pieces, vectors, strict=True)
            ):
                db.add(
                    KnowledgeChunk(
                        document_id=document.id,
                        chunk_index=index,
                        content=text,
                        document_title=document.title,
                        category=document.category,
                        heading=heading,
                        token_estimate=estimate_tokens(text),
                        embedding=vector,
                    )
                )

            document.chunk_count = len(pieces)
            document.embedding_model = (
                f"{embedder.name}:{getattr(embedder, 'model', 'n/a')}"
            )
            document.status = KnowledgeStatus.READY
            document.ingested_at = utcnow()

            record_audit(
                db,
                action=AuditAction.KNOWLEDGE_DOC_INGESTED,
                actor=None,
                actor_email="system",
                entity_type="knowledge_document",
                entity_id=document.id,
                detail={
                    "title": document.title,
                    "chunks": len(pieces),
                    "embedder": document.embedding_model,
                },
            )
            db.commit()
            logger.info(
                "Ingested %s (%s): %d chunk(s)", document.id, document.title, len(pieces)
            )

        except Exception as exc:  # noqa: BLE001 - must never kill the worker
            db.rollback()
            logger.exception("Ingestion failed for document %s", document_id)
            document = db.get(KnowledgeDocument, uuid.UUID(str(document_id)))
            if document is not None:
                document.status = KnowledgeStatus.FAILED
                document.error_message = str(exc)[:1000]
                record_audit(
                    db,
                    action=AuditAction.KNOWLEDGE_INGEST_FAILED,
                    actor=None,
                    actor_email="system",
                    entity_type="knowledge_document",
                    entity_id=document.id,
                    detail={"error": str(exc)[:500]},
                )
                db.commit()
    finally:
        db.close()


def knowledge_base_stats(db: Session) -> dict:
    """Counts for the HR knowledge-base dashboard."""
    documents = db.scalars(select(KnowledgeDocument)).all()
    ready = [d for d in documents if d.status is KnowledgeStatus.READY]
    return {
        "documents_total": len(documents),
        "documents_ready": len(ready),
        "documents_failed": sum(
            1 for d in documents if d.status is KnowledgeStatus.FAILED
        ),
        "documents_published": sum(1 for d in documents if d.is_published),
        "chunks_total": sum(d.chunk_count for d in ready),
    }
