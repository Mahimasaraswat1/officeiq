"""Face-matching interface.

Callers depend only on this module, never on OpenCV directly, so swapping in a
different recogniser (face_recognition, DeepFace, a cloud API) means adding one
class and changing FACE_MATCHER in the environment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FaceMatchOutcome(str, Enum):
    """Why a comparison produced the result it did.

    Distinguishing "no face found" from "faces differ" matters: the first is a
    bad upload the employee can fix, the second is a genuine mismatch for HR.
    """

    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    NO_FACE_IN_PHOTO = "no_face_in_photo"
    NO_FACE_IN_ID = "no_face_in_id"
    MULTIPLE_FACES_IN_PHOTO = "multiple_faces_in_photo"
    ERROR = "error"


@dataclass
class FaceMatchResult:
    outcome: FaceMatchOutcome
    similarity: float | None = None       # cosine similarity, 0.0-1.0
    threshold: float | None = None
    faces_in_photo: int = 0
    faces_in_id: int = 0
    engine: str = "unknown"
    message: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.outcome is FaceMatchOutcome.MATCHED

    @property
    def needs_reupload(self) -> bool:
        """True when the employee can fix this by uploading a better image."""
        return self.outcome in (
            FaceMatchOutcome.NO_FACE_IN_PHOTO,
            FaceMatchOutcome.NO_FACE_IN_ID,
            FaceMatchOutcome.MULTIPLE_FACES_IN_PHOTO,
        )

    def as_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "similarity": self.similarity,
            "threshold": self.threshold,
            "faces_in_photo": self.faces_in_photo,
            "faces_in_id": self.faces_in_id,
            "engine": self.engine,
            "message": self.message,
            **self.detail,
        }


class FaceMatcher:
    """Base class for face-matching engines."""

    name: str = "base"

    def is_available(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError

    def compare(self, photo_bytes: bytes, id_bytes: bytes) -> FaceMatchResult:  # pragma: no cover
        raise NotImplementedError


class FaceMatcherUnavailableError(RuntimeError):
    """Raised when the configured matcher cannot be initialised."""
