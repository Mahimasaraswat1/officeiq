"""Vector retrieval over the knowledge base (PRD B.4.6 query pipeline).

On Postgres this is a pgvector cosine-distance ORDER BY, executed in the
database. On SQLite (the test suite) embeddings are stored as JSON and ranked in
Python, so both paths exercise the same ranking semantics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine
from app.models.enums import KnowledgeCategory, KnowledgeStatus
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.services.embeddings import cosine_similarity, get_embedder, active_embedder_name

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    document_title: str
    source_reference: str | None
    category: str
    heading: str | None
    content: str
    chunk_index: int
    similarity: float

    def as_citation(self) -> dict:
        return {
            "document_id": self.document_id,
            "document_title": self.document_title,
            "source_reference": self.source_reference,
            "heading": self.heading,
            "chunk_index": self.chunk_index,
            "similarity": round(self.similarity, 4),
        }


def _searchable_filters():
    """Only published, fully-ingested documents are retrievable."""
    return [
        KnowledgeDocument.is_published.is_(True),
        KnowledgeDocument.status == KnowledgeStatus.READY,
    ]


def index_mismatches(db: Session) -> list[tuple[str, str | None]]:
    """Searchable documents whose stored vectors came from a different embedder.

    A document embedded by one model and queried by another cannot match at
    any threshold — the two vector spaces are unrelated. Reporting the pairing
    turns a baffling "nothing found" into a one-line diagnosis.
    """
    active = active_embedder_name()
    rows = db.execute(
        select(KnowledgeDocument.title, KnowledgeDocument.embedding_model)
        .where(*_searchable_filters_documents())
    ).all()
    return [
        (title, model)
        for title, model in rows
        if not (model or "").startswith(f"{active}:")
    ]


def _searchable_filters_documents() -> list:
    """Document-level equivalent of the chunk filters used by retrieve()."""
    return [
        KnowledgeDocument.is_published.is_(True),
        KnowledgeDocument.status == KnowledgeStatus.READY,
    ]


def retrieve(
    db: Session,
    query: str,
    *,
    top_k: int | None = None,
    min_similarity: float | None = None,
    category: KnowledgeCategory | None = None,
) -> list[RetrievedChunk]:
    """Return the most relevant chunks for a question, best first."""
    top_k = top_k if top_k is not None else settings.RETRIEVAL_TOP_K
    threshold = (
        min_similarity if min_similarity is not None else settings.RETRIEVAL_MIN_SIMILARITY
    )

    if not query or not query.strip():
        return []

    query_vector = get_embedder().embed_query(query)

    filters = _searchable_filters()
    if category is not None:
        filters.append(KnowledgeChunk.category == category)

    if engine.dialect.name == "postgresql":
        # cosine_distance = 1 - cosine_similarity; ordering by it ascending
        # gives most-similar-first, and pgvector can use an index for it.
        distance = KnowledgeChunk.embedding.cosine_distance(query_vector)
        rows = db.execute(
            select(KnowledgeChunk, KnowledgeDocument, distance.label("distance"))
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(*filters, KnowledgeChunk.embedding.is_not(None))
            .order_by(distance)
            .limit(top_k * 3)  # over-fetch, then filter by threshold
        ).all()
        scored = [
            (chunk, document, 1.0 - float(dist)) for chunk, document, dist in rows
        ]
    else:
        # SQLite: no vector ops, so score in Python.
        rows = db.execute(
            select(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(*filters, KnowledgeChunk.embedding.is_not(None))
        ).all()
        scored = [
            (chunk, document, cosine_similarity(query_vector, chunk.embedding or []))
            for chunk, document in rows
        ]
        scored.sort(key=lambda row: row[2], reverse=True)

    results: list[RetrievedChunk] = []
    for chunk, document, similarity in scored:
        if similarity < threshold:
            continue
        results.append(
            RetrievedChunk(
                chunk_id=str(chunk.id),
                document_id=str(document.id),
                document_title=chunk.document_title,
                source_reference=document.source_reference,
                category=chunk.category.value,
                heading=chunk.heading,
                content=chunk.content,
                chunk_index=chunk.chunk_index,
                similarity=similarity,
            )
        )
        if len(results) >= top_k:
            break

    # An empty result set is the symptom a mismatched index produces, so this
    # is the moment to say whether the index is the reason. Only checked when
    # nothing matched, so the common path costs no extra query.
    if not results:
        mismatched = index_mismatches(db)
        if mismatched:
            logger.error(
                "RETRIEVAL RETURNED NOTHING and %d searchable document(s) are "
                "embedded by a different model than the active one (%r). These "
                "vector spaces are unrelated, so no threshold can match them. "
                "Re-index, or restore the embedder that produced them. "
                "Affected: %s",
                len(mismatched),
                active_embedder_name(),
                ", ".join(f"{title} [{model or 'never embedded'}]" for title, model in mismatched[:5]),
            )

    return results
