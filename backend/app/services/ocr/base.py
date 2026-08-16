"""OCR engine interface.

Everything downstream depends on this interface, never on Tesseract directly,
so swapping in a cloud OCR provider (PRD B.11) means adding one class here and
changing OCR_ENGINE in the environment — no changes to extractors or the API.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OcrWord:
    text: str
    confidence: float  # 0.0-1.0


@dataclass
class OcrResult:
    """Recognised text plus the per-word confidences used to score fields."""

    text: str
    words: list[OcrWord] = field(default_factory=list)
    engine: str = "unknown"

    @property
    def mean_confidence(self) -> float:
        scored = [w.confidence for w in self.words if w.text.strip()]
        if not scored:
            return 0.0
        return round(sum(scored) / len(scored), 4)

    def confidence_for(self, snippet: str) -> float:
        """Average confidence of the words making up `snippet`.

        Falls back to the document mean when the snippet cannot be matched —
        which happens for values assembled by regex across token boundaries.
        """
        needle = "".join(snippet.split()).lower()
        if not needle:
            return 0.0

        matches = [
            w.confidence
            for w in self.words
            if w.text.strip() and "".join(w.text.split()).lower() in needle
        ]
        if not matches:
            return self.mean_confidence
        return round(sum(matches) / len(matches), 4)


class OcrEngine:
    """Base class for OCR providers."""

    name: str = "base"

    def is_available(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def image_to_result(self, image_bytes: bytes) -> OcrResult:  # pragma: no cover
        raise NotImplementedError


class OcrUnavailableError(RuntimeError):
    """Raised when the configured OCR engine cannot be reached."""
