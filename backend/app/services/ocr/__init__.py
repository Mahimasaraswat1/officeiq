"""OCR engine selection and document text extraction."""

from __future__ import annotations

import io
import logging
from functools import lru_cache

from app.core.config import settings
from app.services.ocr.base import OcrEngine, OcrResult, OcrUnavailableError, OcrWord

logger = logging.getLogger(__name__)

PDF_CONTENT_TYPE = "application/pdf"
# A PDF yielding less than this many characters is treated as a scan and
# rasterised for OCR rather than trusted as a text layer.
MIN_PDF_TEXT_CHARS = 40


class StubEngine(OcrEngine):
    """Deterministic no-op engine.

    Lets the upload/extraction pipeline be exercised in CI on machines without
    Tesseract. It returns no text, so extractors simply find no fields.
    """

    name = "stub"

    def is_available(self) -> bool:
        return True

    def image_to_result(self, image_bytes: bytes) -> OcrResult:
        return OcrResult(text="", words=[], engine=self.name)


@lru_cache
def get_ocr_engine() -> OcrEngine:
    if settings.OCR_ENGINE == "stub":
        return StubEngine()

    from app.services.ocr.tesseract import TesseractEngine

    engine = TesseractEngine()
    if not engine.is_available():
        logger.warning(
            "Tesseract is not available on this host — falling back to the stub "
            "engine. Install tesseract or set OCR_ENGINE=stub to silence this."
        )
        return StubEngine()
    return engine


def _pdf_to_result(data: bytes) -> OcrResult:
    """Prefer a PDF's embedded text layer; rasterise and OCR only if absent."""
    import fitz  # PyMuPDF

    with fitz.open(stream=data, filetype="pdf") as pdf:
        text_parts = [page.get_text() for page in pdf]
        embedded = "\n".join(text_parts).strip()

        if len(embedded) >= MIN_PDF_TEXT_CHARS:
            # A real text layer: every character is exact, so confidence is 1.0.
            words = [OcrWord(text=t, confidence=1.0) for t in embedded.split()]
            return OcrResult(text=embedded, words=words, engine="pdf_text")

        engine = get_ocr_engine()
        zoom = settings.OCR_PDF_DPI / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        combined_text: list[str] = []
        combined_words: list[OcrWord] = []
        for page in pdf:
            pixmap = page.get_pixmap(matrix=matrix)
            page_result = engine.image_to_result(pixmap.tobytes("png"))
            if page_result.text:
                combined_text.append(page_result.text)
            combined_words.extend(page_result.words)

        return OcrResult(
            text="\n".join(combined_text), words=combined_words, engine=engine.name
        )


def extract_text(data: bytes, content_type: str) -> OcrResult:
    """Run the right extraction strategy for this file type."""
    if content_type == PDF_CONTENT_TYPE:
        return _pdf_to_result(data)
    return get_ocr_engine().image_to_result(data)


__all__ = [
    "OcrEngine",
    "OcrResult",
    "OcrUnavailableError",
    "OcrWord",
    "StubEngine",
    "extract_text",
    "get_ocr_engine",
]
