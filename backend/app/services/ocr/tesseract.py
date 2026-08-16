"""Self-hosted Tesseract OCR engine."""

from __future__ import annotations

import io
import logging

from app.core.config import settings
from app.services.ocr.base import OcrEngine, OcrResult, OcrUnavailableError, OcrWord

logger = logging.getLogger(__name__)


class TesseractEngine(OcrEngine):
    name = "tesseract"

    def __init__(self) -> None:
        import pytesseract

        self._pytesseract = pytesseract
        if settings.TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

    def is_available(self) -> bool:
        try:
            self._pytesseract.get_tesseract_version()
            return True
        except Exception:  # noqa: BLE001 - any failure means "not usable"
            return False

    def _preprocess(self, image_bytes: bytes):
        """Grayscale + upscale small scans, which measurably helps Tesseract."""
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes))
        if image.mode not in ("L", "RGB"):
            image = image.convert("RGB")
        image = image.convert("L")

        # Tesseract struggles below ~1000px on the long edge.
        longest = max(image.size)
        if longest < 1000:
            scale = 1000 / longest
            image = image.resize(
                (int(image.width * scale), int(image.height * scale)),
                Image.LANCZOS,
            )
        return image

    def image_to_result(self, image_bytes: bytes) -> OcrResult:
        try:
            image = self._preprocess(image_bytes)
            data = self._pytesseract.image_to_data(
                image,
                lang=settings.OCR_LANGUAGES,
                output_type=self._pytesseract.Output.DICT,
            )
        except Exception as exc:  # noqa: BLE001
            raise OcrUnavailableError(f"Tesseract failed: {exc}") from exc

        words: list[OcrWord] = []
        # Group words back into their source lines. Tesseract reports the block,
        # paragraph, and line each word belongs to; without using them the text
        # collapses to a single line and every line-anchored pattern downstream
        # (name labels, resume section headings) silently runs across lines.
        lines: dict[tuple[int, int, int], list[str]] = {}
        line_order: list[tuple[int, int, int]] = []

        columns = zip(
            data.get("text", []),
            data.get("conf", []),
            data.get("block_num", []),
            data.get("par_num", []),
            data.get("line_num", []),
            strict=False,
        )
        for text, raw_conf, block, par, line in columns:
            if not text or not text.strip():
                continue
            try:
                conf = float(raw_conf)
            except (TypeError, ValueError):
                conf = -1.0
            if conf < 0:  # -1 marks a region Tesseract could not score
                continue

            words.append(OcrWord(text=text, confidence=round(conf / 100.0, 4)))

            key = (block, par, line)
            if key not in lines:
                lines[key] = []
                line_order.append(key)
            lines[key].append(text)

        rebuilt = "\n".join(" ".join(lines[key]) for key in line_order)
        return OcrResult(text=rebuilt, words=words, engine=self.name)
