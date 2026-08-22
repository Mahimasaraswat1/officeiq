"""Unit tests for chunking, embeddings, confidence, and the escalation gate.

These run without a database or any API key — they operate on the pure
functions directly, so the RAG logic is pinned independently of Voyage's
embedding quality or Claude's answer quality.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.enums import ChatOutcome
from app.services.chat import (
    LOW_CONFIDENCE_MESSAGE,
    NO_CONTEXT_MESSAGE,
    INSUFFICIENT_MARKER,
    _confidence_from,
    _finalise,
    build_context_block,
)
from app.services.embeddings import LocalHashEmbedder, cosine_similarity
from app.services.knowledge import chunk_document, estimate_tokens
from app.services.retrieval import RetrievedChunk

LEAVE_POLICY = """\
ANNUAL LEAVE ENTITLEMENT
Full-time employees receive 21 days of paid annual leave per calendar year.

CARRY FORWARD
A maximum of 10 unused days may be carried forward. Carried-forward days must be
used by 31 March.

APPLYING FOR LEAVE
Requests must be submitted at least 7 calendar days in advance.
"""


def make_chunk(similarity: float, *, title: str = "Leave Policy", content: str = "text") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="c1",
        document_id="d1",
        document_title=title,
        source_reference="Handbook §4.1",
        category="leave",
        heading="Annual Leave",
        content=content,
        chunk_index=0,
        similarity=similarity,
    )


# --- Chunking --------------------------------------------------------------


def test_chunking_splits_on_headings():
    chunks = chunk_document(LEAVE_POLICY)
    headings = [h for h, _ in chunks]

    assert "ANNUAL LEAVE ENTITLEMENT" in headings
    assert "CARRY FORWARD" in headings
    assert "APPLYING FOR LEAVE" in headings


def test_each_chunk_carries_its_heading_for_context():
    """A bare '21 days' is meaningless to an embedder without its heading."""
    chunks = chunk_document(LEAVE_POLICY)
    entitlement = next(text for heading, text in chunks if heading == "ANNUAL LEAVE ENTITLEMENT")

    assert entitlement.startswith("ANNUAL LEAVE ENTITLEMENT")
    assert "21 days" in entitlement


def test_markdown_headings_are_recognised():
    chunks = chunk_document("# Payroll\n\nSalaries are paid monthly.\n\n## Payslips\n\nIssued in two days.")
    headings = [h for h, _ in chunks]
    assert "Payroll" in headings
    assert "Payslips" in headings


def test_text_without_headings_still_chunks():
    chunks = chunk_document("Just a flat paragraph of policy text with no headings at all.")
    assert len(chunks) == 1
    assert chunks[0][0] is None


def test_long_sections_are_split_with_overlap():
    long_body = "SECTION ONE\n\n" + " ".join(f"Sentence number {i}." for i in range(400))
    chunks = chunk_document(long_body, target_chars=500, overlap_chars=100)

    assert len(chunks) > 1
    assert all(len(text) < 900 for _, text in chunks)


def test_empty_content_produces_no_chunks():
    assert chunk_document("") == []
    assert chunk_document("   \n\n  ") == []


def test_token_estimate_is_positive():
    assert estimate_tokens("hello world") >= 1
    assert estimate_tokens("x" * 4000) > 500


# --- Local embedder --------------------------------------------------------


def test_local_embedder_is_deterministic():
    embedder = LocalHashEmbedder()
    assert embedder.embed_query("annual leave") == embedder.embed_query("annual leave")


def test_local_embedder_returns_configured_dimensions():
    vector = LocalHashEmbedder().embed_query("test")
    assert len(vector) == settings.EMBEDDING_DIMENSIONS


def test_local_embedder_vectors_are_normalised():
    vector = LocalHashEmbedder().embed_query("annual leave policy")
    magnitude = sum(v * v for v in vector) ** 0.5
    assert magnitude == pytest.approx(1.0, abs=1e-6)


def test_related_text_scores_higher_than_unrelated():
    embedder = LocalHashEmbedder()
    query = embedder.embed_query("how many annual leave days do I get")
    related = embedder.embed_query("Employees receive 21 days of annual leave per year")
    unrelated = embedder.embed_query("Laptops are issued on the first working day")

    assert cosine_similarity(query, related) > cosine_similarity(query, unrelated)


def test_cosine_similarity_edge_cases():
    assert cosine_similarity([], []) == 0.0
    assert cosine_similarity([1.0, 0.0], []) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


def test_empty_text_embeds_without_crashing():
    vector = LocalHashEmbedder().embed_query("")
    assert len(vector) == settings.EMBEDDING_DIMENSIONS


# --- Context block ---------------------------------------------------------


def test_context_block_numbers_passages_for_citation():
    block = build_context_block([
        make_chunk(0.9, title="Leave Policy"),
        make_chunk(0.8, title="Payroll Policy"),
    ])
    assert "[1] Leave Policy" in block
    assert "[2] Payroll Policy" in block


def test_context_block_includes_heading_and_source():
    block = build_context_block([make_chunk(0.9)])
    assert "Annual Leave" in block
    assert "Handbook §4.1" in block


# --- Confidence ------------------------------------------------------------


def test_confidence_is_zero_without_context():
    assert _confidence_from([], answered=True) == 0.0


def test_confidence_collapses_when_the_model_cannot_answer():
    """Strong retrieval must not imply confidence if the answer wasn't found."""
    strong = [make_chunk(0.95), make_chunk(0.92)]
    assert _confidence_from(strong, answered=True) > 0.9
    assert _confidence_from(strong, answered=False) == 0.0


def test_confidence_tracks_retrieval_strength():
    high = _confidence_from([make_chunk(0.9), make_chunk(0.85)], answered=True)
    low = _confidence_from([make_chunk(0.5), make_chunk(0.4)], answered=True)
    assert high > low


def test_confidence_is_bounded():
    assert 0.0 <= _confidence_from([make_chunk(1.0)], answered=True) <= 1.0
    assert 0.0 <= _confidence_from([make_chunk(0.0)], answered=True) <= 1.0


# --- Escalation gate -------------------------------------------------------


def _finalise_with(text: str, chunks):
    return _finalise(
        text=text, chunks=chunks, model="test",
        input_tokens=1, output_tokens=1, latency_ms=1,
    )


def test_insufficient_context_marker_escalates():
    """The model saying it can't answer must never reach the employee raw."""
    result = _finalise_with(INSUFFICIENT_MARKER, [make_chunk(0.95)])

    assert result.outcome is ChatOutcome.ESCALATED_NO_CONTEXT
    assert result.escalated is True
    assert result.confidence == 0.0
    assert result.text == NO_CONTEXT_MESSAGE
    assert INSUFFICIENT_MARKER not in result.text
    assert result.citations == []


def test_empty_answer_escalates():
    result = _finalise_with("", [make_chunk(0.95)])
    assert result.escalated is True
    assert result.outcome is ChatOutcome.ESCALATED_NO_CONTEXT


def test_weak_retrieval_escalates_even_with_an_answer(monkeypatch):
    """A confident-sounding answer built on weak context must not be served."""
    monkeypatch.setattr(settings, "CHAT_ESCALATION_THRESHOLD", 0.9)
    result = _finalise_with("Employees get 21 days. [1]", [make_chunk(0.5)])

    assert result.outcome is ChatOutcome.ESCALATED_LOW_CONFIDENCE
    assert result.escalated is True
    # A near-miss is a different situation from nothing being found, and the
    # employee is told which one happened.
    assert result.text == LOW_CONFIDENCE_MESSAGE
    assert result.text != NO_CONTEXT_MESSAGE
    # Citations are retained so HR can see what was retrieved.
    assert len(result.citations) == 1


def test_strong_answer_is_served_with_citations(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_ESCALATION_THRESHOLD", 0.4)
    result = _finalise_with("Employees receive 21 days. [1]", [make_chunk(0.9)])

    assert result.outcome is ChatOutcome.ANSWERED
    assert result.escalated is False
    assert "21 days" in result.text
    assert result.citations[0]["document_title"] == "Leave Policy"
    assert result.citations[0]["source_reference"] == "Handbook §4.1"


def test_marker_detection_is_case_insensitive():
    result = _finalise_with("insufficient_context", [make_chunk(0.95)])
    assert result.escalated is True
