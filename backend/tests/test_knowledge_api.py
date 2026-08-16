"""Knowledge base admin, ingestion, retrieval, and the chatbot API."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.enums import AuditAction
from app.models.knowledge import ChatConversation, KnowledgeChunk, KnowledgeDocument
from tests.conftest import API

LEAVE_DOC = {
    "title": "Annual Leave Policy",
    "category": "leave",
    "source_reference": "Employee Handbook §4.1",
    "content": """\
ANNUAL LEAVE ENTITLEMENT
Full-time employees receive 21 days of paid annual leave per calendar year.
Leave accrues at 1.75 days per completed month of service.

CARRY FORWARD
A maximum of 10 unused annual leave days may be carried forward into the next
calendar year. Carried-forward days must be used by 31 March.
""",
}

IT_DOC = {
    "title": "IT Equipment Policy",
    "category": "it",
    "source_reference": "IT Policy §1",
    "content": """\
EQUIPMENT ISSUE
Laptops and accessories are issued on the first working day. Equipment remains
company property and must be returned on the last working day.

PASSWORDS AND SECURITY
Multi-factor authentication is mandatory on email and all systems holding
employee data. Report a lost or stolen device to IT immediately.
""",
}


def create_doc(client, headers, payload):
    return client.post(f"{API}/knowledge/documents", json=payload, headers=headers)


@pytest.fixture
def employee_headers(client, hr_headers):
    """An activated employee account (the chatbot's actual audience)."""
    created = client.post(
        f"{API}/employees",
        json={
            "first_name": "Ananya",
            "last_name": "Sharma",
            "work_email": "ananya.chat@example.com",
        },
        headers=hr_headers,
    )
    assert created.status_code == 201
    files = sorted(Path(settings.EMAIL_OUTBOX_DIR).glob("*.txt"))
    token = re.search(r"accept-invite\?token=([A-Za-z0-9_\-]+)", files[-1].read_text()).group(1)
    client.post(f"{API}/onboarding/accept", json={"token": token, "password": "Ananya@12345"})
    tokens = client.post(
        f"{API}/auth/login",
        json={"email": "ananya.chat@example.com", "password": "Ananya@12345"},
    ).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# --- Document administration -----------------------------------------------


def test_hr_can_add_a_document_and_it_is_ingested(client, hr_headers, db):
    response = create_doc(client, hr_headers, LEAVE_DOC)
    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "ready"
    assert body["chunk_count"] >= 2
    assert body["embedding_model"].startswith("local")

    chunks = db.scalars(select(KnowledgeChunk)).all()
    assert len(chunks) == body["chunk_count"]
    assert all(c.embedding is not None for c in chunks)


def test_chunks_carry_denormalised_citation_metadata(client, hr_headers, db):
    create_doc(client, hr_headers, LEAVE_DOC)
    chunk = db.scalar(select(KnowledgeChunk))

    assert chunk.document_title == "Annual Leave Policy"
    assert chunk.category.value == "leave"
    assert chunk.heading is not None


def test_short_content_is_rejected(client, hr_headers):
    response = create_doc(client, hr_headers, {**LEAVE_DOC, "content": "Too short."})
    assert response.status_code == 422


def test_employee_cannot_manage_the_knowledge_base(client, employee_headers):
    assert client.get(f"{API}/knowledge/documents", headers=employee_headers).status_code == 403
    assert create_doc(client, employee_headers, LEAVE_DOC).status_code == 403
    assert client.get(f"{API}/knowledge/stats", headers=employee_headers).status_code == 403


def test_editing_content_triggers_reingestion(client, hr_headers, db):
    document = create_doc(client, hr_headers, LEAVE_DOC).json()
    original_chunks = document["chunk_count"]

    response = client.patch(
        f"{API}/knowledge/documents/{document['id']}",
        json={"content": LEAVE_DOC["content"] + "\n\nSICK LEAVE\nTwelve days per year.\n"},
        headers=hr_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["chunk_count"] > original_chunks


def test_editing_only_metadata_does_not_reingest(client, hr_headers):
    document = create_doc(client, hr_headers, LEAVE_DOC).json()

    response = client.patch(
        f"{API}/knowledge/documents/{document['id']}",
        json={"version": "2026.2"},
        headers=hr_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["chunk_count"] == document["chunk_count"]


def test_reingest_is_idempotent(client, hr_headers, db):
    document = create_doc(client, hr_headers, LEAVE_DOC).json()
    before = db.scalars(select(KnowledgeChunk)).all()

    client.post(f"{API}/knowledge/documents/{document['id']}/reingest", headers=hr_headers)
    db.expire_all()
    after = db.scalars(select(KnowledgeChunk)).all()

    assert len(after) == len(before)


def test_deleting_a_document_removes_its_chunks(client, hr_headers, db):
    document = create_doc(client, hr_headers, LEAVE_DOC).json()
    assert db.scalars(select(KnowledgeChunk)).all()

    assert client.delete(
        f"{API}/knowledge/documents/{document['id']}", headers=hr_headers
    ).status_code == 200

    db.expire_all()
    assert db.scalars(select(KnowledgeChunk)).all() == []


def test_ingestion_failure_is_recorded_not_raised(client, hr_headers, monkeypatch):
    """A broken embedder must surface as a failed document, never a 500."""
    import app.services.knowledge as knowledge_service

    class BrokenEmbedder:
        name = "broken"

        def embed_documents(self, texts):
            raise RuntimeError("simulated embedding outage")

    monkeypatch.setattr(knowledge_service, "get_embedder", lambda: BrokenEmbedder())

    response = create_doc(client, hr_headers, LEAVE_DOC)
    assert response.status_code == 201
    assert response.json()["status"] == "failed"
    assert "simulated embedding outage" in response.json()["error_message"]


def test_knowledge_actions_are_audited(client, hr_headers, db):
    create_doc(client, hr_headers, LEAVE_DOC)

    actions = {row.action for row in db.scalars(select(AuditLog)).all()}
    assert AuditAction.KNOWLEDGE_DOC_CREATED.value in actions
    assert AuditAction.KNOWLEDGE_DOC_INGESTED.value in actions


def test_stats_reports_providers(client, hr_headers):
    create_doc(client, hr_headers, LEAVE_DOC)

    stats = client.get(f"{API}/knowledge/stats", headers=hr_headers).json()
    assert stats["documents_ready"] == 1
    assert stats["chunks_total"] > 0
    assert stats["embedding_provider"] == "local"
    assert stats["chat_provider"] == "stub"


# --- Retrieval -------------------------------------------------------------


def test_retrieval_finds_the_relevant_document(client, hr_headers):
    create_doc(client, hr_headers, LEAVE_DOC)
    create_doc(client, hr_headers, IT_DOC)

    response = client.post(
        f"{API}/knowledge/search",
        json={"query": "how many annual leave days do employees get"},
        headers=hr_headers,
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results, "expected at least one retrieval hit"
    assert results[0]["document_title"] == "Annual Leave Policy"


def test_retrieval_results_are_ordered_by_similarity(client, hr_headers):
    create_doc(client, hr_headers, LEAVE_DOC)
    create_doc(client, hr_headers, IT_DOC)

    results = client.post(
        f"{API}/knowledge/search",
        json={"query": "annual leave carry forward days", "top_k": 10},
        headers=hr_headers,
    ).json()["results"]

    scores = [r["similarity"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_retrieval_can_be_filtered_by_category(client, hr_headers):
    create_doc(client, hr_headers, LEAVE_DOC)
    create_doc(client, hr_headers, IT_DOC)

    results = client.post(
        f"{API}/knowledge/search",
        json={"query": "policy", "top_k": 10, "category": "it"},
        headers=hr_headers,
    ).json()["results"]

    assert all(r["category"] == "it" for r in results)


def test_unpublished_documents_are_not_retrievable(client, hr_headers):
    document = create_doc(client, hr_headers, LEAVE_DOC).json()

    client.patch(
        f"{API}/knowledge/documents/{document['id']}",
        json={"is_published": False},
        headers=hr_headers,
    )

    results = client.post(
        f"{API}/knowledge/search",
        json={"query": "annual leave entitlement days"},
        headers=hr_headers,
    ).json()["results"]
    assert results == []


def test_retrieval_on_an_empty_knowledge_base_returns_nothing(client, hr_headers):
    results = client.post(
        f"{API}/knowledge/search", json={"query": "anything"}, headers=hr_headers
    ).json()
    assert results["total"] == 0


# --- Chat ------------------------------------------------------------------


def test_employee_gets_a_grounded_answer_with_citations(client, hr_headers, employee_headers):
    create_doc(client, hr_headers, LEAVE_DOC)

    response = client.post(
        f"{API}/chat/ask",
        json={"question": "How many annual leave days do I get per year?"},
        headers=employee_headers,
    )
    assert response.status_code == 201

    body = response.json()
    assert body["outcome"] == "answered"
    assert body["escalated"] is False
    assert body["confidence"] > 0
    assert body["citations"], "an answered response must carry citations"
    assert body["citations"][0]["document_title"] == "Annual Leave Policy"
    assert body["citations"][0]["source_reference"] == "Employee Handbook §4.1"


def test_question_with_no_knowledge_base_escalates_to_hr(client, employee_headers):
    """PRD A.7.6: escalate rather than answer from thin air."""
    response = client.post(
        f"{API}/chat/ask",
        json={"question": "What is the parental leave policy?"},
        headers=employee_headers,
    )
    assert response.status_code == 201

    body = response.json()
    assert body["outcome"] == "escalated_no_context"
    assert body["escalated"] is True
    assert body["confidence"] == 0.0
    assert body["citations"] == []
    assert "HR" in body["answer"]
    assert body["escalation_hint"] is not None


def test_offtopic_question_escalates_rather_than_forcing_an_answer(
    client, hr_headers, employee_headers
):
    create_doc(client, hr_headers, LEAVE_DOC)

    body = client.post(
        f"{API}/chat/ask",
        json={"question": "zzzz qqqq xylophone quokka nonsense token"},
        headers=employee_headers,
    ).json()

    assert body["escalated"] is True
    assert body["outcome"].startswith("escalated")


def test_escalation_is_audited_with_the_reason(client, employee_headers, db):
    client.post(
        f"{API}/chat/ask",
        json={"question": "What is the sabbatical policy?"},
        headers=employee_headers,
    )

    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.CHAT_ESCALATED_TO_HR.value)
    )
    assert entry is not None
    assert entry.detail["reason"].startswith("escalated")


def test_conversation_threads_turns_together(client, hr_headers, employee_headers):
    create_doc(client, hr_headers, LEAVE_DOC)

    first = client.post(
        f"{API}/chat/ask",
        json={"question": "How many annual leave days do I get?"},
        headers=employee_headers,
    ).json()

    second = client.post(
        f"{API}/chat/ask",
        json={
            "question": "And how many can I carry forward?",
            "conversation_id": first["conversation_id"],
        },
        headers=employee_headers,
    ).json()

    assert second["conversation_id"] == first["conversation_id"]

    detail = client.get(
        f"{API}/chat/conversations/{first['conversation_id']}", headers=employee_headers
    ).json()
    # Two questions and two answers.
    assert len(detail["messages"]) == 4
    assert [m["role"] for m in detail["messages"]] == [
        "user", "assistant", "user", "assistant"
    ]


def test_conversations_are_private_to_their_owner(client, hr_headers, employee_headers):
    """Even HR must not read an employee's chat history through this API."""
    conversation_id = client.post(
        f"{API}/chat/ask", json={"question": "Anything?"}, headers=employee_headers
    ).json()["conversation_id"]

    assert client.get(
        f"{API}/chat/conversations/{conversation_id}", headers=hr_headers
    ).status_code == 403
    assert client.delete(
        f"{API}/chat/conversations/{conversation_id}", headers=hr_headers
    ).status_code == 403


def test_asking_requires_authentication(client):
    assert client.post(f"{API}/chat/ask", json={"question": "Hi"}).status_code == 401


def test_blank_question_is_rejected(client, employee_headers):
    assert client.post(
        f"{API}/chat/ask", json={"question": "   "}, headers=employee_headers
    ).status_code == 422


def test_employee_can_delete_their_own_conversation(client, employee_headers, db):
    conversation_id = client.post(
        f"{API}/chat/ask", json={"question": "Anything?"}, headers=employee_headers
    ).json()["conversation_id"]

    assert client.delete(
        f"{API}/chat/conversations/{conversation_id}", headers=employee_headers
    ).status_code == 200

    db.expire_all()
    assert db.scalars(select(ChatConversation)).all() == []


def test_analytics_reports_the_resolution_rate(client, hr_headers, employee_headers):
    """The KPI maths. Asserts the two asks classified as expected first, so a
    retrieval-quality change fails here loudly instead of silently shifting the
    ratio (the local test embedder is phrasing-sensitive — see the note in
    app/services/embeddings.py).
    """
    create_doc(client, hr_headers, LEAVE_DOC)

    answered = client.post(
        f"{API}/chat/ask",
        json={"question": "How many annual leave days do I get per year?"},
        headers=employee_headers,
    ).json()
    escalated = client.post(
        f"{API}/chat/ask",
        json={"question": "What is the sabbatical policy?"},
        headers=employee_headers,
    ).json()

    assert answered["outcome"] == "answered", answered
    assert escalated["escalated"] is True, escalated

    analytics = client.get(f"{API}/chat/analytics", headers=hr_headers).json()
    assert analytics["questions_total"] == 2
    assert analytics["answered"] == 1
    assert analytics["escalated"] == 1
    assert analytics["resolution_rate"] == 0.5
    assert analytics["escalations_by_reason"]["escalated_no_context"] == 1


def test_analytics_is_hr_only(client, employee_headers):
    assert client.get(f"{API}/chat/analytics", headers=employee_headers).status_code == 403
