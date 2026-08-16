"""OpenCV DNN face matching: YuNet for detection, SFace for recognition.

Both models are small ONNX files shipped by the OpenCV Zoo and run on CPU, so
there is no compile step and no framework install — the reason this engine was
chosen over dlib/DeepFace for v1.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import settings
from app.services.face.base import (
    FaceMatcher,
    FaceMatcherUnavailableError,
    FaceMatchOutcome,
    FaceMatchResult,
)

logger = logging.getLogger(__name__)

# YuNet is trained at this input size; larger images are scaled to fit.
DETECTOR_INPUT_SIZE = (320, 320)
MAX_EDGE = 1024


class OpenCvDnnFaceMatcher(FaceMatcher):
    name = "opencv_dnn"

    def __init__(self) -> None:
        self._detector = None
        self._recognizer = None

    # --- Model loading -----------------------------------------------------

    @property
    def detector_path(self) -> Path:
        return Path(settings.FACE_MODEL_DIR) / settings.FACE_DETECTOR_MODEL

    @property
    def recognizer_path(self) -> Path:
        return Path(settings.FACE_MODEL_DIR) / settings.FACE_RECOGNIZER_MODEL

    def is_available(self) -> bool:
        if not (self.detector_path.is_file() and self.recognizer_path.is_file()):
            return False
        try:
            self._load()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _load(self) -> None:
        if self._detector is not None and self._recognizer is not None:
            return

        import cv2

        if not self.detector_path.is_file() or not self.recognizer_path.is_file():
            raise FaceMatcherUnavailableError(
                "Face models are missing. Run: python scripts/download_face_models.py"
            )

        self._detector = cv2.FaceDetectorYN.create(
            str(self.detector_path),
            "",
            DETECTOR_INPUT_SIZE,
            settings.FACE_DETECTION_CONFIDENCE,
        )
        self._recognizer = cv2.FaceRecognizerSF.create(str(self.recognizer_path), "")

    # --- Image helpers -----------------------------------------------------

    def _decode(self, data: bytes):
        """Decode bytes to a BGR array, downscaling very large images."""
        import cv2
        import numpy as np

        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Could not decode the image")

        height, width = image.shape[:2]
        longest = max(height, width)
        if longest > MAX_EDGE:
            scale = MAX_EDGE / longest
            image = cv2.resize(
                image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA
            )
        return image

    def _detect(self, image):
        """Return detected faces sorted by descending detector score."""
        height, width = image.shape[:2]
        self._detector.setInputSize((width, height))
        _, faces = self._detector.detect(image)
        if faces is None or len(faces) == 0:
            return []
        # Column 14 is YuNet's confidence score.
        return sorted(faces, key=lambda f: float(f[-1]), reverse=True)

    def _embed(self, image, face):
        aligned = self._recognizer.alignCrop(image, face)
        return self._recognizer.feature(aligned)

    # --- Comparison --------------------------------------------------------

    def compare(self, photo_bytes: bytes, id_bytes: bytes) -> FaceMatchResult:
        import cv2

        threshold = settings.FACE_MATCH_THRESHOLD

        try:
            self._load()
            photo = self._decode(photo_bytes)
            id_image = self._decode(id_bytes)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Face matching could not start")
            return FaceMatchResult(
                outcome=FaceMatchOutcome.ERROR,
                threshold=threshold,
                engine=self.name,
                message=str(exc)[:300],
            )

        try:
            photo_faces = self._detect(photo)
            id_faces = self._detect(id_image)

            if not photo_faces:
                return FaceMatchResult(
                    outcome=FaceMatchOutcome.NO_FACE_IN_PHOTO,
                    threshold=threshold,
                    faces_in_id=len(id_faces),
                    engine=self.name,
                    message=(
                        "No face was detected in the uploaded photo. "
                        "Please upload a clear, front-facing photo."
                    ),
                )

            if not id_faces:
                return FaceMatchResult(
                    outcome=FaceMatchOutcome.NO_FACE_IN_ID,
                    threshold=threshold,
                    faces_in_photo=len(photo_faces),
                    engine=self.name,
                    message=(
                        "No face was detected on the ID document. "
                        "Please upload a clearer scan showing the photo on the ID."
                    ),
                )

            # More than one face in a passport photo means we cannot be sure
            # whose face we compared — surface it rather than guessing.
            if len(photo_faces) > 1:
                return FaceMatchResult(
                    outcome=FaceMatchOutcome.MULTIPLE_FACES_IN_PHOTO,
                    threshold=threshold,
                    faces_in_photo=len(photo_faces),
                    faces_in_id=len(id_faces),
                    engine=self.name,
                    message=(
                        f"{len(photo_faces)} faces were detected in the photo. "
                        "Please upload a photo containing only the employee."
                    ),
                )

            photo_feature = self._embed(photo, photo_faces[0])
            id_feature = self._embed(id_image, id_faces[0])

            similarity = float(
                self._recognizer.match(
                    photo_feature, id_feature, cv2.FaceRecognizerSF_FR_COSINE
                )
            )
            similarity = round(max(0.0, min(1.0, similarity)), 4)
            matched = similarity >= threshold

            return FaceMatchResult(
                outcome=(
                    FaceMatchOutcome.MATCHED if matched else FaceMatchOutcome.NOT_MATCHED
                ),
                similarity=similarity,
                threshold=threshold,
                faces_in_photo=len(photo_faces),
                faces_in_id=len(id_faces),
                engine=self.name,
                message=(
                    f"Face similarity {similarity:.3f} "
                    f"{'meets' if matched else 'is below'} the {threshold:.3f} threshold."
                ),
                detail={
                    "photo_detection_score": round(float(photo_faces[0][-1]), 4),
                    "id_detection_score": round(float(id_faces[0][-1]), 4),
                },
            )

        except Exception as exc:  # noqa: BLE001
            logger.exception("Face matching failed")
            return FaceMatchResult(
                outcome=FaceMatchOutcome.ERROR,
                threshold=threshold,
                engine=self.name,
                message=str(exc)[:300],
            )
