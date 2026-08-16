"""Face matcher selection."""

from __future__ import annotations

import logging
from functools import lru_cache

from app.core.config import settings
from app.services.face.base import (
    FaceMatcher,
    FaceMatcherUnavailableError,
    FaceMatchOutcome,
    FaceMatchResult,
)

logger = logging.getLogger(__name__)


class StubFaceMatcher(FaceMatcher):
    """Deterministic no-op matcher for CI hosts without the ONNX models.

    Returns ERROR rather than a fake score: a fabricated "match" would be worse
    than an honest "could not run", since HR would act on it.
    """

    name = "stub"

    def is_available(self) -> bool:
        return True

    def compare(self, photo_bytes: bytes, id_bytes: bytes) -> FaceMatchResult:
        return FaceMatchResult(
            outcome=FaceMatchOutcome.ERROR,
            threshold=settings.FACE_MATCH_THRESHOLD,
            engine=self.name,
            message=(
                "Face matching is not configured on this server "
                "(FACE_MATCHER=stub). Manual HR review is required."
            ),
        )


@lru_cache
def get_face_matcher() -> FaceMatcher:
    if settings.FACE_MATCHER == "stub":
        return StubFaceMatcher()

    from app.services.face.opencv_dnn import OpenCvDnnFaceMatcher

    matcher = OpenCvDnnFaceMatcher()
    if not matcher.is_available():
        logger.warning(
            "OpenCV face models are unavailable — falling back to the stub matcher. "
            "Run `python scripts/download_face_models.py` to enable face matching."
        )
        return StubFaceMatcher()
    return matcher


def compare_faces(photo_bytes: bytes, id_bytes: bytes) -> FaceMatchResult:
    return get_face_matcher().compare(photo_bytes, id_bytes)


__all__ = [
    "FaceMatchOutcome",
    "FaceMatchResult",
    "FaceMatcher",
    "FaceMatcherUnavailableError",
    "StubFaceMatcher",
    "compare_faces",
    "get_face_matcher",
]
