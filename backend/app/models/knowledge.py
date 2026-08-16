"""Knowledge base documents, embedded chunks, and chatbot conversations.

Chunk embeddings live in a pgvector column alongside the rest of the relational
data, so retrieval is an ordinary SQL query with an ORDER BY on vector distance
— no second datastore to keep in sync (PRD B.2 vector store choice).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from app.core.config import settings
from app.core.database import Base
from app.core.types import TZDateTime
from app.models.enums import ChatOutcome, ChatRole, KnowledgeCategory, KnowledgeStatus
from app.models.user import User

json_type = JSON().with_variant(JSONB(), "postgresql")

knowledge_category_enum = SAEnum(
    KnowledgeCategory,
    name="knowledge_category",
    values_callable=lambda e: [m.value for m in e],
)
knowledge_status_enum = SAEnum(
    KnowledgeStatus, name="knowledge_status", values_callable=lambda e: [m.value for m in e]
)
chat_role_enum = SAEnum(
    ChatRole, name="chat_role", values_callable=lambda e: [m.value for m in e]
)
chat_outcome_enum = SAEnum(
    ChatOutcome, name="chat_outcome", values_callable=lambda e: [m.value for m in e]
)

# SQLite has no vector type; the test suite stores the embedding as JSON and
# ranks in Python, so the same code paths run on both backends.
embedding_type = Vector(settings.EMBEDDING_DIMENSIONS).with_variant(JSON(), "sqlite")


class KnowledgeDocument(Base):
    """One curated source document (a policy, handbook section, FAQ)."""

    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[KnowledgeCategory] = mapped_column(
        knowledge_category_enum, nullable=False, index=True
    )
    # The full source text. Kept so a document can be re-chunked when the
    # chunking strategy or embedding model changes.
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Shown beside answers so employees can see where a claim came from.
    source_reference: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[str | None] = mapped_column(String(32))

    status: Mapped[KnowledgeStatus] = mapped_column(
        knowledge_status_enum, default=KnowledgeStatus.PENDING, nullable=False, index=True
    )
    # Only published documents are retrievable — lets HR stage a draft.
    is_published: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )

    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Recorded per document so a provider/model change is detectable.
    embedding_model: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    ingested_at: Mapped[datetime | None] = mapped_column(TZDateTime)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    @property
    def is_searchable(self) -> bool:
        return self.is_published and self.status is KnowledgeStatus.READY

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<KnowledgeDocument {self.title!r} {self.status.value}>"


class KnowledgeChunk(Base):
    """A retrievable slice of a document, with its embedding."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_per_document"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Denormalised so a retrieval hit can be cited without a second query.
    document_title: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[KnowledgeCategory] = mapped_column(
        knowledge_category_enum, nullable=False, index=True
    )
    heading: Mapped[str | None] = mapped_column(String(255))
    token_estimate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    embedding: Mapped[list[float] | None] = mapped_column(embedding_type)

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<KnowledgeChunk {self.document_title!r} #{self.chunk_index}>"


class ChatConversation(Base):
    """A chat thread between one user and the assistant."""

    __tablename__ = "chat_conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200))

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), index=True, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship()
    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    """One turn. Assistant turns carry their citations and confidence."""

    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("chat_conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role: Mapped[ChatRole] = mapped_column(chat_role_enum, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # --- Assistant-turn metadata ------------------------------------------
    outcome: Mapped[ChatOutcome | None] = mapped_column(chat_outcome_enum, index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    # [{document_id, document_title, source_reference, chunk_index, similarity}]
    citations: Mapped[list | None] = mapped_column(json_type)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    model: Mapped[str | None] = mapped_column(String(64))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), index=True, nullable=False
    )

    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")
