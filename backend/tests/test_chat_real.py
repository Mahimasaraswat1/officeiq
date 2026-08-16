"""Live tests against the real Claude API and real Voyage embeddings.

Each group skips automatically when its key is absent, so CI stays green
without credentials. These are the PRD B.7 "chatbot evaluation — sample Q&A set
checked for grounded, correct, policy-consistent answers" tests.

The assertions deliberately check *grounding* (does it use the passage, does it
refuse when the passage doesn't cover the question) rather than exact wording,
which would be brittle against a generative model.
"""

from __future__ import annotations

import os

import pytest

from app.core.config import settings
from app.models.enums import ChatOutcome
from app.services.retrieval import RetrievedChunk

HAS_ANTHROPIC_KEY = bool(
    os.environ.get("ANTHROPIC_API_KEY") or settings.ANTHROPIC_API_KEY
)
HAS_VOYAGE_KEY = bool(os.environ.get("VOYAGE_API_KEY") or settings.VOYAGE_API_KEY)

LEAVE_PASSAGE = (
    "ANNUAL LEAVE ENTITLEMENT\n\n"
    "Full-time employees receive 21 days of paid annual leave per calendar year. "
    "Leave accrues at 1.75 days per completed month of service. A maximum of 10 "
    "unused days may be carried forward and must be used by 31 March."
)


def passage(content: str = LEAVE_PASSAGE, similarity: float = 0.85) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        document_title="Annual Leave Policy",
        source_reference="Employee Handbook §4.1",
        category="leave",
        heading="Annual Leave Entitlement",
        content=content,
        chunk_index=0,
        similarity=similarity,
    )


# --- Claude generation -----------------------------------------------------

claude = pytest.mark.skipif(
    not HAS_ANTHROPIC_KEY, reason="ANTHROPIC_API_KEY not set — skipping live Claude tests"
)


@pytest.fixture
def claude_generator(monkeypatch):
    from app.services import chat as chat_service

    monkeypatch.setattr(settings, "CHAT_PROVIDER", "claude")
    return chat_service.ClaudeGenerator()


@claude
def test_claude_answers_from_the_provided_passage(claude_generator):
    result = claude_generator.generate(
        "How many days of annual leave do I get each year?", [passage()]
    )

    assert result.outcome is ChatOutcome.ANSWERED, result.text
    assert "21" in result.text
    assert result.escalated is False
    assert result.citations
    assert result.model and result.model.startswith("claude")


@claude
def test_claude_refuses_what_the_passage_does_not_cover(claude_generator):
    """The core anti-hallucination guarantee (PRD A.11).

    The passage is about annual leave; parental leave is not in it. A model
    answering from general knowledge about how companies usually work would be
    inventing this company's policy.
    """
    result = claude_generator.generate(
        "How many weeks of paid parental leave does the company give?", [passage()]
    )

    assert result.escalated is True, f"model should not have answered: {result.text}"
    assert result.outcome is ChatOutcome.ESCALATED_NO_CONTEXT
    # The employee sees the escalation message, never the raw marker.
    assert "INSUFFICIENT_CONTEXT" not in result.text
    assert "HR" in result.text


@claude
def test_claude_does_not_invent_figures_absent_from_the_passage(claude_generator):
    narrow = passage(
        content="CARRY FORWARD\n\nUnused annual leave may be carried forward "
        "into the next calendar year and must be used by 31 March."
    )
    result = claude_generator.generate(
        "Exactly how many annual leave days can I carry forward?", narrow and [narrow]
    )

    # The passage states the rule but not the number; a specific figure here
    # would be fabricated.
    if not result.escalated:
        assert "10" not in result.text, f"invented a figure: {result.text}"


@claude
def test_claude_cites_the_passage_it_used(claude_generator):
    result = claude_generator.generate("What is the annual leave entitlement?", [passage()])
    assert "[1]" in result.text, result.text


@claude
def test_claude_answer_reports_usage_and_latency(claude_generator):
    result = claude_generator.generate("What is the leave entitlement?", [passage()])

    assert result.input_tokens and result.input_tokens > 0
    assert result.output_tokens and result.output_tokens > 0
    assert result.latency_ms is not None and result.latency_ms >= 0


@claude
def test_claude_through_the_api_end_to_end(client, hr_headers, monkeypatch):
    """Full path: ingest → retrieve → Claude → citations, over HTTP."""
    import re
    from pathlib import Path

    from tests.conftest import API

    monkeypatch.setattr(settings, "CHAT_PROVIDER", "claude")

    created = client.post(
        f"{API}/knowledge/documents",
        json={
            "title": "Annual Leave Policy",
            "category": "leave",
            "source_reference": "Employee Handbook §4.1",
            "content": LEAVE_PASSAGE,
        },
        headers=hr_headers,
    )
    assert created.status_code == 201
    assert created.json()["status"] == "ready"

    employee = client.post(
        f"{API}/employees",
        json={
            "first_name": "Live",
            "last_name": "Tester",
            "work_email": "live.chat@example.com",
        },
        headers=hr_headers,
    )
    assert employee.status_code == 201
    files = sorted(Path(settings.EMAIL_OUTBOX_DIR).glob("*.txt"))
    token = re.search(r"accept-invite\?token=([A-Za-z0-9_\-]+)", files[-1].read_text()).group(1)
    client.post(f"{API}/onboarding/accept", json={"token": token, "password": "Live@123456"})
    tokens = client.post(
        f"{API}/auth/login",
        json={"email": "live.chat@example.com", "password": "Live@123456"},
    ).json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    response = client.post(
        f"{API}/chat/ask",
        json={"question": "How many annual leave days do I get per calendar year?"},
        headers=headers,
    )
    assert response.status_code == 201

    body = response.json()
    assert body["outcome"] == "answered", body
    assert "21" in body["answer"]
    assert body["citations"][0]["document_title"] == "Annual Leave Policy"


# --- Voyage embeddings -----------------------------------------------------

voyage = pytest.mark.skipif(
    not HAS_VOYAGE_KEY, reason="VOYAGE_API_KEY not set — skipping live Voyage tests"
)


@pytest.fixture
def voyage_embedder(monkeypatch):
    from app.services.embeddings import VoyageEmbedder

    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "voyage")
    return VoyageEmbedder()


@voyage
def test_voyage_returns_configured_dimensions(voyage_embedder):
    vector = voyage_embedder.embed_query("annual leave entitlement")
    assert len(vector) == settings.EMBEDDING_DIMENSIONS


@voyage
def test_voyage_matches_paraphrases_the_local_embedder_misses(voyage_embedder):
    """The reason Voyage is the production default.

    "time off" never appears in the passage, so a lexical embedder scores it
    near zero. A real embedding model should rank it above an unrelated policy.
    """
    from app.services.embeddings import cosine_similarity

    query = voyage_embedder.embed_query("how much time off am I allowed")
    docs = voyage_embedder.embed_documents([
        LEAVE_PASSAGE,
        "EQUIPMENT ISSUE\n\nLaptops are issued on the first working day and "
        "remain company property.",
    ])

    leave_score = cosine_similarity(query, docs[0])
    it_score = cosine_similarity(query, docs[1])
    assert leave_score > it_score, f"leave={leave_score:.3f} it={it_score:.3f}"


@voyage
def test_voyage_batches_beyond_the_request_limit(voyage_embedder):
    from app.services.embeddings import VOYAGE_MAX_BATCH

    texts = [f"Policy clause number {i} about workplace conduct." for i in range(VOYAGE_MAX_BATCH + 5)]
    vectors = voyage_embedder.embed_documents(texts)

    assert len(vectors) == len(texts)
    assert all(len(v) == settings.EMBEDDING_DIMENSIONS for v in vectors)
