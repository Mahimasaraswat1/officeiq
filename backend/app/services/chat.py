"""Grounded answer generation, plus HR escalation (PRD A.7.6).

Providers are interchangeable: Claude, Groq, or a deterministic stub for CI.
A provider only turns a question plus retrieved passages into text — every
grounding rule lives in the shared code below.

The model is instructed to answer *only* from retrieved context and to say so
when the context does not cover the question. Combined with the confidence
gate below, that is what keeps the bot from inventing policy — the failure mode
the PRD calls out as the top chatbot risk (A.11).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.core.config import settings
from app.models.enums import ChatOutcome
from app.services.retrieval import RetrievedChunk

logger = logging.getLogger(__name__)

# The marker the model is told to emit when the context can't answer the
# question. Detecting it is more reliable than trying to parse a hedge.
INSUFFICIENT_MARKER = "INSUFFICIENT_CONTEXT"

SYSTEM_PROMPT = f"""\
You are OfficeIQ's HR assistant. You answer employee questions about company \
policy, leave, payroll, benefits, and onboarding.

Answer using ONLY the numbered context passages provided in the user message. \
Those passages are the company's own policy documents and are the sole source \
of truth available to you.

Rules:
- If the passages do not contain enough information to answer, reply with \
exactly {INSUFFICIENT_MARKER} and nothing else. Do not guess, and do not fall \
back on general knowledge about how companies usually work — a plausible \
answer that isn't this company's policy is worse than no answer.
- Cite the passages you used inline as [1], [2], matching their numbers.
- Never invent figures, dates, entitlements, or policy names. If a passage is \
close but does not actually answer what was asked, say what it does cover and \
reply {INSUFFICIENT_MARKER}.
- Do not give legal, tax, or medical advice. For anything requiring individual \
judgement or an exception to policy, tell the employee to contact HR.
- Be concise and direct. Two or three sentences is usually enough. Use the \
employee's own terms rather than restating policy headings.
"""


@dataclass
class ChatAnswer:
    text: str
    outcome: ChatOutcome
    confidence: float
    citations: list[dict] = field(default_factory=list)
    escalated: bool = False
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    error: str | None = None


ESCALATION_MESSAGE = (
    "I couldn't find that in the company knowledge base, so I don't want to guess. "
    "Please contact your HR team — they can confirm the current policy for your case."
)


def build_context_block(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as numbered passages the model can cite."""
    parts = []
    for index, chunk in enumerate(chunks, start=1):
        label = chunk.document_title
        if chunk.heading:
            label = f"{label} — {chunk.heading}"
        if chunk.source_reference:
            label = f"{label} ({chunk.source_reference})"
        parts.append(f"[{index}] {label}\n{chunk.content}")
    return "\n\n".join(parts)


def _confidence_from(chunks: list[RetrievedChunk], answered: bool) -> float:
    """Blend retrieval strength with whether the model could actually answer.

    Retrieval similarity alone overstates confidence — a strong lexical match
    can still fail to contain the answer — so a model that emits the
    insufficient-context marker collapses the score regardless of similarity.
    """
    if not chunks:
        return 0.0
    if not answered:
        return 0.0

    best = chunks[0].similarity
    mean = sum(c.similarity for c in chunks) / len(chunks)
    # Weight the best hit most; the mean rewards corroboration across passages.
    score = 0.7 * best + 0.3 * mean
    return round(max(0.0, min(1.0, score)), 4)


class ChatGenerator:
    """Base class for answer generators."""

    name = "base"

    def generate(self, question: str, chunks: list[RetrievedChunk],
                 history: list[dict] | None = None) -> ChatAnswer:  # pragma: no cover
        raise NotImplementedError


class ClaudeGenerator(ChatGenerator):
    """Generation via the Anthropic Messages API."""

    name = "claude"

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic

            if not settings.ANTHROPIC_API_KEY:
                # The SDK also resolves ANTHROPIC_API_KEY / an `ant auth login`
                # profile from the environment, so try a bare client too.
                self._client = anthropic.Anthropic()
            else:
                self._client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        return self._client

    def generate(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        history: list[dict] | None = None,
    ) -> ChatAnswer:
        import anthropic

        started = time.monotonic()
        context = build_context_block(chunks)
        user_content = (
            f"Context passages:\n\n{context}\n\n"
            f"---\n\nEmployee question: {question}"
        )

        messages: list[dict] = []
        for turn in history or []:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_content})

        try:
            response = self._get_client().messages.create(
                model=settings.CHAT_MODEL,
                max_tokens=settings.CHAT_MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        # The system prompt is identical on every request, so
                        # caching it makes each answer cheaper after the first.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                thinking={"type": "adaptive"},
                output_config={"effort": settings.CHAT_EFFORT},
                messages=messages,
            )
        except anthropic.APIStatusError as exc:
            logger.exception("Claude API error")
            return ChatAnswer(
                text=ESCALATION_MESSAGE,
                outcome=ChatOutcome.ERROR,
                confidence=0.0,
                escalated=True,
                error=f"{exc.status_code}: {exc.message}"[:500],
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Claude call failed")
            return ChatAnswer(
                text=ESCALATION_MESSAGE,
                outcome=ChatOutcome.ERROR,
                confidence=0.0,
                escalated=True,
                error=str(exc)[:500],
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        latency_ms = int((time.monotonic() - started) * 1000)

        # A safety refusal is not an answer — escalate rather than surface it.
        if response.stop_reason == "refusal":
            return ChatAnswer(
                text=ESCALATION_MESSAGE,
                outcome=ChatOutcome.ERROR,
                confidence=0.0,
                escalated=True,
                model=response.model,
                error="model declined to answer",
                latency_ms=latency_ms,
            )

        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

        usage = getattr(response, "usage", None)
        return _finalise(
            text=text,
            chunks=chunks,
            model=response.model,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            latency_ms=latency_ms,
        )


class GroqGenerator(ChatGenerator):
    """Generation via Groq's OpenAI-compatible chat completions API.

    Groq is a drop-in alternative to Claude here because every grounding rule
    lives outside the provider: the system prompt, the numbered context block,
    the insufficient-context marker and the confidence gate are all shared, and
    this class only has to return the model's text plus its token usage. Swap
    the provider and the anti-hallucination behaviour is unchanged.

    The one structural difference from the Anthropic client is that the system
    prompt is an ordinary message rather than a separate parameter.
    """

    name = "groq"

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            from groq import Groq

            # The SDK also picks GROQ_API_KEY up from the environment, so a
            # bare client still works when the setting is unset.
            self._client = (
                Groq(api_key=settings.GROQ_API_KEY)
                if settings.GROQ_API_KEY
                else Groq()
            )
        return self._client

    def generate(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        history: list[dict] | None = None,
    ) -> ChatAnswer:
        import groq

        started = time.monotonic()
        context = build_context_block(chunks)
        user_content = (
            f"Context passages:\n\n{context}\n\n"
            f"---\n\nEmployee question: {question}"
        )

        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history or []:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append({"role": "user", "content": user_content})

        try:
            response = self._get_client().chat.completions.create(
                model=settings.GROQ_MODEL,
                max_tokens=settings.CHAT_MAX_TOKENS,
                messages=messages,
                # Near-deterministic: this is grounded extraction from supplied
                # passages, not creative writing, and a policy answer should not
                # vary between identical questions.
                temperature=0.1,
            )
        except groq.APIStatusError as exc:
            logger.exception("Groq API error")
            return ChatAnswer(
                text=ESCALATION_MESSAGE,
                outcome=ChatOutcome.ERROR,
                confidence=0.0,
                escalated=True,
                error=f"{exc.status_code}: {exc.message}"[:500],
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Groq call failed")
            return ChatAnswer(
                text=ESCALATION_MESSAGE,
                outcome=ChatOutcome.ERROR,
                confidence=0.0,
                escalated=True,
                error=str(exc)[:500],
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        choice = response.choices[0] if response.choices else None

        # Groq's equivalent of a refusal. Surfacing a filtered response as an
        # answer would be worse than handing the question to HR.
        if choice is not None and choice.finish_reason == "content_filter":
            return ChatAnswer(
                text=ESCALATION_MESSAGE,
                outcome=ChatOutcome.ERROR,
                confidence=0.0,
                escalated=True,
                model=response.model,
                error="model declined to answer",
                latency_ms=latency_ms,
            )

        text = ((choice.message.content if choice else None) or "").strip()

        usage = getattr(response, "usage", None)
        return _finalise(
            text=text,
            chunks=chunks,
            model=response.model,
            # OpenAI-style names for the same two numbers Claude reports.
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            latency_ms=latency_ms,
        )


class StubGenerator(ChatGenerator):
    """Deterministic generator for CI — no API key, no network.

    Quotes the top retrieved passage rather than inventing prose, so tests
    exercise the retrieval → citation → confidence path honestly without
    claiming to test Claude's answer quality.
    """

    name = "stub"

    def generate(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        history: list[dict] | None = None,
    ) -> ChatAnswer:
        if not chunks:
            return ChatAnswer(
                text=ESCALATION_MESSAGE,
                outcome=ChatOutcome.ESCALATED_NO_CONTEXT,
                confidence=0.0,
                escalated=True,
                model="stub",
                latency_ms=0,
            )

        excerpt = chunks[0].content.strip().replace("\n", " ")[:300]
        return _finalise(
            text=f"{excerpt} [1]",
            chunks=chunks,
            model="stub",
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
        )


def _finalise(
    *,
    text: str,
    chunks: list[RetrievedChunk],
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    latency_ms: int | None,
) -> ChatAnswer:
    """Apply the insufficient-context marker and the confidence gate."""
    said_insufficient = INSUFFICIENT_MARKER in text.upper()
    answered = bool(text) and not said_insufficient

    confidence = _confidence_from(chunks, answered)

    if said_insufficient or not text:
        return ChatAnswer(
            text=ESCALATION_MESSAGE,
            outcome=ChatOutcome.ESCALATED_NO_CONTEXT,
            confidence=0.0,
            citations=[],
            escalated=True,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

    if confidence < settings.CHAT_ESCALATION_THRESHOLD:
        # The model produced an answer, but retrieval was too weak to trust it.
        return ChatAnswer(
            text=ESCALATION_MESSAGE,
            outcome=ChatOutcome.ESCALATED_LOW_CONFIDENCE,
            confidence=confidence,
            citations=[c.as_citation() for c in chunks],
            escalated=True,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

    return ChatAnswer(
        text=text,
        outcome=ChatOutcome.ANSWERED,
        confidence=confidence,
        citations=[c.as_citation() for c in chunks],
        escalated=False,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=latency_ms,
    )


def get_generator() -> ChatGenerator:
    if settings.CHAT_PROVIDER == "stub":
        return StubGenerator()
    if settings.CHAT_PROVIDER == "groq":
        return GroqGenerator()
    return ClaudeGenerator()


def answer_question(
    question: str,
    chunks: list[RetrievedChunk],
    history: list[dict] | None = None,
) -> ChatAnswer:
    """Generate a grounded answer, escalating when context is missing."""
    if not chunks:
        return ChatAnswer(
            text=ESCALATION_MESSAGE,
            outcome=ChatOutcome.ESCALATED_NO_CONTEXT,
            confidence=0.0,
            escalated=True,
        )
    return get_generator().generate(question, chunks, history)
