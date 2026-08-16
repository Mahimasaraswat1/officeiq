"""Knowledge base and chatbot schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ChatOutcome, ChatRole, KnowledgeCategory, KnowledgeStatus

MIN_CONTENT_LENGTH = 20
MAX_QUESTION_LENGTH = 2000


# --- Knowledge documents ---------------------------------------------------


class KnowledgeDocumentBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: KnowledgeCategory = KnowledgeCategory.POLICY
    source_reference: str | None = Field(
        default=None,
        max_length=255,
        description="Where this came from, e.g. 'Employee Handbook v3, §4.2'",
    )
    version: str | None = Field(default=None, max_length=32)
    is_published: bool = True


class KnowledgeDocumentCreate(KnowledgeDocumentBase):
    content: str = Field(min_length=MIN_CONTENT_LENGTH)

    @field_validator("content")
    @classmethod
    def _meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < MIN_CONTENT_LENGTH:
            raise ValueError(
                f"Content must be at least {MIN_CONTENT_LENGTH} characters of "
                "actual policy text."
            )
        return cleaned


class KnowledgeDocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    category: KnowledgeCategory | None = None
    content: str | None = Field(default=None, min_length=MIN_CONTENT_LENGTH)
    source_reference: str | None = Field(default=None, max_length=255)
    version: str | None = Field(default=None, max_length=32)
    is_published: bool | None = None


class KnowledgeDocumentRead(KnowledgeDocumentBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: KnowledgeStatus
    chunk_count: int
    embedding_model: str | None = None
    error_message: str | None = None
    ingested_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentDetail(KnowledgeDocumentRead):
    content: str


class KnowledgeStats(BaseModel):
    documents_total: int
    documents_ready: int
    documents_failed: int
    documents_published: int
    chunks_total: int
    embedding_provider: str
    chat_provider: str
    chat_model: str


# --- Retrieval preview (HR tooling) ----------------------------------------


class RetrievalPreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    top_k: int = Field(default=5, ge=1, le=20)
    category: KnowledgeCategory | None = None


class RetrievedChunkRead(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    source_reference: str | None = None
    heading: str | None = None
    category: str
    chunk_index: int
    similarity: float
    content: str


class RetrievalPreviewResponse(BaseModel):
    query: str
    results: list[RetrievedChunkRead] = Field(default_factory=list)
    total: int = 0


# --- Chat ------------------------------------------------------------------


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    conversation_id: uuid.UUID | None = Field(
        default=None, description="Continue an existing thread; omit to start a new one"
    )
    category: KnowledgeCategory | None = Field(
        default=None, description="Restrict retrieval to one knowledge category"
    )

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Please enter a question.")
        return cleaned


class CitationRead(BaseModel):
    document_id: str
    document_title: str
    source_reference: str | None = None
    heading: str | None = None
    chunk_index: int
    similarity: float


class ChatMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: ChatRole
    content: str
    outcome: ChatOutcome | None = None
    confidence: float | None = None
    citations: list[CitationRead] | None = None
    escalated: bool = False
    created_at: datetime


class AskResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    outcome: ChatOutcome
    confidence: float
    citations: list[CitationRead] = Field(default_factory=list)
    escalated: bool
    # Shown to the employee when the bot escalates, so the hand-off is explicit.
    escalation_hint: str | None = None
    model: str | None = None
    latency_ms: int | None = None


class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None = None
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationRead):
    messages: list[ChatMessageRead] = Field(default_factory=list)


class ChatAnalytics(BaseModel):
    """Feeds the PRD A.10 "resolution rate without HR escalation" KPI."""

    questions_total: int
    answered: int
    escalated: int
    resolution_rate: float
    average_confidence: float | None = None
    escalations_by_reason: dict[str, int] = Field(default_factory=dict)
