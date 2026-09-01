"""The employee-facing RAG chatbot (PRD A.7.6)."""

from __future__ import annotations

import logging

import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, HrUser
from app.core.errors import NotFoundError, PermissionDeniedError
from app.core.ratelimit import chat_rate_limit
from app.models.enums import AuditAction, ChatOutcome, ChatRole, UserRole
from app.models.knowledge import ChatConversation, ChatMessage
from app.schemas.common import Message
from app.schemas.knowledge import (
    AskRequest,
    AskResponse,
    ChatAnalytics,
    ChatMessageRead,
    ConversationDetail,
    ConversationRead,
)
from app.services.audit import record_audit
from app.services.chat import ChatAnswer, SERVICE_ERROR_MESSAGE, answer_question
from app.services.embeddings import EmbeddingError
from app.services.notifications import notify_chat_escalated
from app.services.retrieval import retrieve

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["AI Assistant"])

# How many prior turns to replay as conversational context.
HISTORY_TURNS = 6
TITLE_MAX = 80

# The hint the UI shows alongside an escalation. It follows the reason, so a
# technical fault does not send the employee chasing HR about a policy gap.
ESCALATION_HINTS = {
    ChatOutcome.ESCALATED_NO_CONTEXT: (
        "Contact your HR team for this one — they can confirm the policy for your "
        "specific situation."
    ),
    ChatOutcome.ESCALATED_LOW_CONFIDENCE: (
        "Related passages are listed below, but check with HR before relying on them."
    ),
    ChatOutcome.ERROR: (
        "Nothing is wrong with your question — please try again shortly."
    ),
}


def _get_conversation(db: DbSession, conversation_id: uuid.UUID, user) -> ChatConversation:
    conversation = db.get(ChatConversation, conversation_id)
    if conversation is None:
        raise NotFoundError("Conversation not found.")
    # A conversation is private to the employee who had it, HR included.
    if conversation.user_id != user.id:
        raise PermissionDeniedError("You can only access your own conversations.")
    return conversation


@router.post(
    "/ask",
    response_model=AskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ask the assistant a question",
    # Per-user: every question costs a model call, in money.
    dependencies=[Depends(chat_rate_limit)],
)
def ask(
    payload: AskRequest, request: Request, db: DbSession, user: CurrentUser
) -> AskResponse:
    if payload.conversation_id is not None:
        conversation = _get_conversation(db, payload.conversation_id, user)
    else:
        conversation = ChatConversation(
            user_id=user.id, title=payload.question[:TITLE_MAX]
        )
        db.add(conversation)
        db.flush()

    db.add(
        ChatMessage(
            conversation_id=conversation.id,
            role=ChatRole.USER,
            content=payload.question,
        )
    )
    db.flush()

    # Replay recent turns so follow-ups like "and for part-timers?" resolve.
    history_rows = db.scalars(
        select(ChatMessage)
        .where(
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.role.in_([ChatRole.USER, ChatRole.ASSISTANT]),
        )
        .order_by(ChatMessage.created_at.desc())
        .limit(HISTORY_TURNS + 1)
    ).all()
    # Drop the question just inserted; it is passed separately with context.
    history = [
        {"role": m.role.value, "content": m.content}
        for m in reversed(history_rows)
        if not (m.role is ChatRole.USER and m.content == payload.question)
    ][-HISTORY_TURNS:]

    # Retrieval reaches an external embedding API, so it can fail for reasons
    # that have nothing to do with the question — the free tier's 3 req/min cap
    # is the one that actually bites. Without this the employee gets a raw 500
    # instead of the "temporarily unavailable" message, and the cause is lost.
    try:
        chunks = retrieve(db, payload.question, category=payload.category)
    except EmbeddingError as exc:
        logger.exception("Retrieval failed for a chat question")
        result = ChatAnswer(
            text=SERVICE_ERROR_MESSAGE,
            outcome=ChatOutcome.ERROR,
            confidence=0.0,
            escalated=True,
            error=f"retrieval failed: {exc}",
        )
    else:
        result = answer_question(payload.question, chunks, history)

    assistant_message = ChatMessage(
        conversation_id=conversation.id,
        role=ChatRole.ASSISTANT,
        content=result.text,
        outcome=result.outcome,
        confidence=result.confidence,
        citations=result.citations or None,
        escalated=result.escalated,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        latency_ms=result.latency_ms,
        # Stored, not shown: the employee gets the outcome-appropriate message
        # while the cause stays queryable for whoever has to fix it.
        error_message=result.error,
    )
    db.add(assistant_message)
    db.flush()

    record_audit(
        db,
        action=AuditAction.CHAT_QUESTION_ASKED,
        actor=user,
        entity_type="chat_conversation",
        entity_id=conversation.id,
        detail={
            "outcome": result.outcome.value,
            "error": result.error,
            "confidence": result.confidence,
            "citations": len(result.citations),
            "model": result.model,
        },
        request=request,
    )
    if result.escalated:
        record_audit(
            db,
            action=AuditAction.CHAT_ESCALATED_TO_HR,
            actor=user,
            entity_type="chat_conversation",
            entity_id=conversation.id,
            detail={
                "reason": result.outcome.value,
                "confidence": result.confidence,
                "question": payload.question[:300],
            },
            request=request,
        )
        notify_chat_escalated(
            db, asker=user, question=payload.question, reason=result.outcome.value
        )

    db.commit()
    db.refresh(assistant_message)

    return AskResponse(
        conversation_id=conversation.id,
        message_id=assistant_message.id,
        answer=result.text,
        outcome=result.outcome,
        confidence=result.confidence,
        citations=result.citations,
        escalated=result.escalated,
        escalation_hint=ESCALATION_HINTS.get(result.outcome) if result.escalated else None,
        model=result.model,
        latency_ms=result.latency_ms,
    )


@router.get(
    "/conversations",
    response_model=list[ConversationRead],
    summary="My conversations",
)
def list_conversations(
    db: DbSession, user: CurrentUser, limit: int = Query(default=20, ge=1, le=100)
) -> list[ConversationRead]:
    rows = db.scalars(
        select(ChatConversation)
        .where(ChatConversation.user_id == user.id)
        .order_by(ChatConversation.updated_at.desc())
        .limit(limit)
    ).all()
    return [ConversationRead.model_validate(row) for row in rows]


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    summary="One conversation with its full transcript",
)
def get_conversation(
    conversation_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> ConversationDetail:
    conversation = _get_conversation(db, conversation_id, user)
    return ConversationDetail(
        **ConversationRead.model_validate(conversation).model_dump(),
        messages=[ChatMessageRead.model_validate(m) for m in conversation.messages],
    )


@router.delete(
    "/conversations/{conversation_id}",
    response_model=Message,
    summary="Delete one of my conversations",
)
def delete_conversation(
    conversation_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Message:
    conversation = _get_conversation(db, conversation_id, user)
    db.delete(conversation)
    db.commit()
    return Message(message="Conversation deleted.")


@router.get(
    "/analytics",
    response_model=ChatAnalytics,
    summary="Chatbot resolution rate and escalations (HR)",
)
def analytics(db: DbSession, _: HrUser) -> ChatAnalytics:
    """PRD A.10: "chatbot query resolution rate without HR escalation"."""
    rows = db.execute(
        select(ChatMessage.outcome, func.count(), func.avg(ChatMessage.confidence))
        .where(ChatMessage.role == ChatRole.ASSISTANT, ChatMessage.outcome.is_not(None))
        .group_by(ChatMessage.outcome)
    ).all()

    counts = {outcome.value: count for outcome, count, _ in rows}
    # Greetings are not questions. Counting them as answered would inflate the
    # resolution rate; counting them as escalations would understate it. They
    # leave the denominator entirely.
    counts.pop(ChatOutcome.SMALL_TALK.value, None)
    total = sum(counts.values())
    answered = counts.get(ChatOutcome.ANSWERED.value, 0)
    escalated = total - answered

    weighted = [
        (count, float(avg)) for _, count, avg in rows if avg is not None
    ]
    average_confidence = (
        round(sum(c * a for c, a in weighted) / sum(c for c, _ in weighted), 4)
        if weighted
        else None
    )

    return ChatAnalytics(
        questions_total=total,
        answered=answered,
        escalated=escalated,
        resolution_rate=round(answered / total, 4) if total else 0.0,
        average_confidence=average_confidence,
        escalations_by_reason={
            key: value for key, value in counts.items() if key != ChatOutcome.ANSWERED.value
        },
    )
