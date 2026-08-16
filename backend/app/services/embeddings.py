"""Text embeddings behind a pluggable provider interface.

**The Claude API has no embeddings endpoint** — it is Messages-only. Anthropic's
documented recommendation is Voyage AI, which is what `voyage` uses here. Claude
handles generation (see app/services/chat.py); embeddings come from this module.

`local` is a deterministic hashing embedder: no API key, no network, identical
vectors on every run. It exists so the ingestion and retrieval pipeline can be
tested end-to-end in CI. Its retrieval quality is far below a real embedding
model — it matches on lexical overlap, not meaning — so it is never a
recommended production setting.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from functools import lru_cache

from app.core.config import settings

logger = logging.getLogger(__name__)

# Voyage's documented ceiling per request; batches are chunked to fit.
VOYAGE_MAX_BATCH = 128


class EmbeddingError(RuntimeError):
    """Raised when embeddings cannot be produced."""


class Embedder:
    """Base class for embedding providers."""

    name: str = "base"
    dimensions: int = settings.EMBEDDING_DIMENSIONS

    def is_available(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def embed_documents(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:  # pragma: no cover
        raise NotImplementedError


class VoyageEmbedder(Embedder):
    """Voyage AI — Anthropic's recommended embeddings partner."""

    name = "voyage"

    def __init__(self) -> None:
        self.model = settings.VOYAGE_MODEL
        self.dimensions = settings.EMBEDDING_DIMENSIONS
        self._client = None

    def _get_client(self):
        if self._client is None:
            import voyageai

            if not settings.VOYAGE_API_KEY:
                raise EmbeddingError(
                    "VOYAGE_API_KEY is not set. Set it, or switch "
                    "EMBEDDING_PROVIDER=local to run without an embeddings API."
                )
            self._client = voyageai.Client(api_key=settings.VOYAGE_API_KEY)
        return self._client

    def is_available(self) -> bool:
        return bool(settings.VOYAGE_API_KEY)

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        client = self._get_client()
        vectors: list[list[float]] = []

        # Voyage caps how many texts one call may carry.
        for start in range(0, len(texts), VOYAGE_MAX_BATCH):
            batch = texts[start : start + VOYAGE_MAX_BATCH]
            try:
                result = client.embed(batch, model=self.model, input_type=input_type)
            except Exception as exc:  # noqa: BLE001
                raise EmbeddingError(f"Voyage embedding failed: {exc}") from exc
            vectors.extend(result.embeddings)

        if vectors and len(vectors[0]) != self.dimensions:
            raise EmbeddingError(
                f"{self.model} returned {len(vectors[0])}-dimensional vectors but "
                f"EMBEDDING_DIMENSIONS is {self.dimensions}. Update the setting and "
                "re-run the migration — the pgvector column width must match."
            )
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # Voyage embeds documents and queries differently; using the right
        # input_type on each side measurably improves retrieval.
        return self._embed(texts, "document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]


class LocalHashEmbedder(Embedder):
    """Deterministic hashing embedder — no key, no network, stable output.

    Projects token hashes into a fixed-width vector with sublinear term
    weighting, then L2-normalises. That makes cosine similarity behave like
    weighted lexical overlap: good enough to prove retrieval ranking works,
    nowhere near a trained model's semantic matching.
    """

    name = "local"

    def __init__(self) -> None:
        self.dimensions = settings.EMBEDDING_DIMENSIONS

    def is_available(self) -> bool:
        return True

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-z0-9]+", text.lower())

    def _vector(self, text: str) -> list[float]:
        counts: dict[int, float] = {}
        tokens = self._tokenize(text)

        for token in tokens:
            # Two independent buckets per token reduce collision damage.
            digest = hashlib.sha256(token.encode()).digest()
            for offset in (0, 8):
                index = int.from_bytes(digest[offset : offset + 8], "big") % self.dimensions
                sign = 1.0 if digest[offset] % 2 == 0 else -1.0
                counts[index] = counts.get(index, 0.0) + sign

        vector = [0.0] * self.dimensions
        for index, raw in counts.items():
            # Sublinear scaling keeps a repeated word from dominating.
            vector[index] = math.copysign(1.0 + math.log(abs(raw)), raw) if raw else 0.0

        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


@lru_cache
def get_embedder() -> Embedder:
    if settings.EMBEDDING_PROVIDER == "local":
        return LocalHashEmbedder()

    embedder = VoyageEmbedder()
    if not embedder.is_available():
        logger.warning(
            "VOYAGE_API_KEY is not set — falling back to the local hashing "
            "embedder. Retrieval quality will be poor; set the key or set "
            "EMBEDDING_PROVIDER=local explicitly to silence this."
        )
        return LocalHashEmbedder()
    return embedder


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity for the SQLite path, where pgvector isn't available."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
