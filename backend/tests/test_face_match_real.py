"""Real face-matching tests against the OpenCV DNN models (YuNet + SFace).

Skipped automatically when the ONNX models are absent (fetch them with
`python scripts/download_face_models.py`), so CI stays green either way.

**Scope, stated plainly.** Fixtures are procedurally drawn faces, so no real
person's biometric data is committed. That covers detection, self-matching,
scale invariance, the not-a-face paths, and our own threshold/decision logic.

It does NOT prove SFace tells two real people apart: synthetic faces are too
similar to one another (measured cosine similarity between different generated
faces is ~0.50-0.77, well above the 0.363 threshold). Discrimination between
real individuals is a property of the SFace model itself, covered by its
published benchmarks — not something these fixtures can demonstrate. The
`different faces` case below therefore drives our decision logic via the
threshold rather than claiming the model separates the images.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.services.face.base import FaceMatchOutcome
from tests.face_fixtures import draw_face

MODEL_DIR = Path(settings.FACE_MODEL_DIR)
MODELS_PRESENT = (
    (MODEL_DIR / settings.FACE_DETECTOR_MODEL).is_file()
    and (MODEL_DIR / settings.FACE_RECOGNIZER_MODEL).is_file()
)

pytestmark = pytest.mark.skipif(
    not MODELS_PRESENT,
    reason="Face models missing — run scripts/download_face_models.py",
)

# Seeds verified to produce a face YuNet reliably detects.
DETECTABLE_SEEDS = (0, 1, 2, 3, 5, 6, 7)


@pytest.fixture(autouse=True)
def _use_real_matcher(monkeypatch):
    from app.services import face

    monkeypatch.setattr(settings, "FACE_MATCHER", "opencv_dnn")
    face.get_face_matcher.cache_clear()
    yield
    face.get_face_matcher.cache_clear()


# --- Engine ----------------------------------------------------------------


def test_opencv_matcher_is_selected_and_available():
    from app.services.face import get_face_matcher

    matcher = get_face_matcher()
    assert matcher.name == "opencv_dnn"
    assert matcher.is_available()


# --- Detection -------------------------------------------------------------


@pytest.mark.parametrize("seed", DETECTABLE_SEEDS)
def test_generated_faces_are_detected(seed):
    from app.services.face import compare_faces

    result = compare_faces(draw_face(seed=seed), draw_face(seed=seed))
    assert result.faces_in_photo == 1, result.message
    assert result.faces_in_id == 1


def test_face_on_a_full_id_card_scan_is_detected():
    """Regression: the detection threshold must suit real ID scans.

    A photo embedded in a full card scan is small and low-contrast, scoring
    ~0.80-0.85 on YuNet even when perfectly legible. A 0.85 detection threshold
    rejected these outright, so every ID card reported "no face on the ID".
    """
    import io

    from PIL import Image

    from app.services.face import compare_faces
    from tests.factories import AADHAAR_TEXT, make_text_image

    # Compose a card the way a real Aadhaar looks: text block plus a photo.
    card = Image.open(
        io.BytesIO(make_text_image(AADHAAR_TEXT, width=1200, height=700))
    ).convert("RGB")
    face = Image.open(io.BytesIO(draw_face(seed=0, size=300))).convert("RGB")
    card.paste(face, (860, 60))
    buffer = io.BytesIO()
    card.save(buffer, format="PNG")

    result = compare_faces(draw_face(seed=0), buffer.getvalue())

    assert result.faces_in_id == 1, result.message
    assert result.outcome is FaceMatchOutcome.MATCHED, result.message


def test_no_face_in_photo_is_reported_distinctly():
    """A blank upload is a fixable mistake, not a mismatch — codes must differ."""
    from app.services.face import compare_faces
    from tests.factories import make_png

    result = compare_faces(make_png(400, 400), draw_face(seed=0))
    assert result.outcome is FaceMatchOutcome.NO_FACE_IN_PHOTO
    assert result.needs_reupload
    assert not result.passed
    assert "photo" in result.message.lower()


def test_no_face_in_id_is_reported_distinctly():
    from app.services.face import compare_faces
    from tests.factories import make_png

    result = compare_faces(draw_face(seed=0), make_png(400, 400))
    assert result.outcome is FaceMatchOutcome.NO_FACE_IN_ID
    assert result.needs_reupload


def test_undecodable_image_is_an_error_not_a_match():
    from app.services.face import compare_faces

    result = compare_faces(b"not an image at all", draw_face(seed=0))
    assert result.outcome is FaceMatchOutcome.ERROR
    assert not result.passed
    assert not result.needs_reupload


# --- Matching --------------------------------------------------------------


def test_identical_faces_match():
    from app.services.face import compare_faces

    face = draw_face(seed=0)
    result = compare_faces(face, face)

    assert result.outcome is FaceMatchOutcome.MATCHED, result.message
    assert result.similarity >= result.threshold
    assert result.similarity == pytest.approx(1.0, abs=0.01)


def test_same_face_at_a_different_scale_still_matches():
    """A passport photo and an ID scan are never the same resolution."""
    from app.services.face import compare_faces

    result = compare_faces(draw_face(seed=0, size=480), draw_face(seed=0, size=300))

    assert result.outcome is FaceMatchOutcome.MATCHED, result.message
    # Rescaling costs some similarity but must stay comfortably above threshold.
    assert result.similarity > 0.7


def test_similarity_below_threshold_produces_not_matched(monkeypatch):
    """Our decision logic, driven via the threshold.

    Synthetic faces cannot be pushed below SFace's default threshold, so the
    threshold is raised above the observed score instead. This pins the
    comparison and the resulting outcome, which is the part we own.
    """
    from app.services.face import compare_faces

    baseline = compare_faces(draw_face(seed=0), draw_face(seed=3))
    assert baseline.similarity is not None

    monkeypatch.setattr(settings, "FACE_MATCH_THRESHOLD", baseline.similarity + 0.05)
    strict = compare_faces(draw_face(seed=0), draw_face(seed=3))

    assert strict.outcome is FaceMatchOutcome.NOT_MATCHED
    assert strict.similarity < strict.threshold
    assert not strict.passed
    assert not strict.needs_reupload  # a mismatch is HR's call, not a re-upload


def test_threshold_is_recorded_with_every_result():
    """A stored score is meaningless later without the threshold it was judged by."""
    from app.services.face import compare_faces

    result = compare_faces(draw_face(seed=0), draw_face(seed=0))
    assert result.threshold == settings.FACE_MATCH_THRESHOLD
    assert result.engine == "opencv_dnn"


def test_similarity_is_bounded_between_zero_and_one():
    from app.services.face import compare_faces

    result = compare_faces(draw_face(seed=0), draw_face(seed=3))
    assert 0.0 <= result.similarity <= 1.0


# --- Through the API -------------------------------------------------------


def test_face_match_through_the_api(client, hr_headers, monkeypatch):
    from tests.conftest import API
    from tests.factories import upload_file

    monkeypatch.setattr(settings, "FACE_MATCHER", "opencv_dnn")

    employee = client.post(
        f"{API}/employees",
        json={
            "first_name": "Ananya",
            "last_name": "Sharma",
            "work_email": "face.test@example.com",
        },
        headers=hr_headers,
    ).json()

    face = draw_face(seed=0)
    upload_file(client, hr_headers, employee["id"], data=face,
                filename="photo.png", document_type="photo")
    upload_file(client, hr_headers, employee["id"], data=face,
                filename="aadhaar.png", document_type="aadhaar")

    response = client.post(
        f"{API}/employees/{employee['id']}/face-match", headers=hr_headers
    )
    assert response.status_code == 201, response.text

    body = response.json()
    assert body["status"] == "matched", body["message"]
    assert body["similarity"] >= body["threshold"]
    assert body["engine"] == "opencv_dnn"

    # The result is persisted as history, not just returned.
    history = client.get(
        f"{API}/employees/{employee['id']}/face-matches", headers=hr_headers
    ).json()
    assert len(history) >= 1
    assert history[0]["threshold"] == body["threshold"]


def test_face_match_against_a_pdf_id_scan(client, hr_headers, monkeypatch):
    """An Aadhaar uploaded as a PDF must be rasterised before matching."""
    import fitz

    from tests.conftest import API
    from tests.factories import upload_file

    monkeypatch.setattr(settings, "FACE_MATCHER", "opencv_dnn")

    face = draw_face(seed=0)
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(60, 60, 540, 540), stream=face)
    pdf_bytes = document.tobytes()
    document.close()

    employee = client.post(
        f"{API}/employees",
        json={
            "first_name": "Pdf",
            "last_name": "Scan",
            "work_email": "pdf.scan@example.com",
        },
        headers=hr_headers,
    ).json()

    upload_file(client, hr_headers, employee["id"], data=face,
                filename="photo.png", document_type="photo")
    upload_file(client, hr_headers, employee["id"], data=pdf_bytes,
                filename="aadhaar.pdf", document_type="aadhaar",
                content_type="application/pdf")

    response = client.post(
        f"{API}/employees/{employee['id']}/face-match", headers=hr_headers
    )
    assert response.status_code == 201
    assert response.json()["status"] == "matched", response.json()["message"]


def test_face_match_requires_both_a_photo_and_an_id(client, hr_headers):
    from tests.conftest import API
    from tests.factories import upload_file

    employee = client.post(
        f"{API}/employees",
        json={
            "first_name": "Solo",
            "last_name": "Photo",
            "work_email": "solo.photo@example.com",
        },
        headers=hr_headers,
    ).json()

    upload_file(client, hr_headers, employee["id"], data=draw_face(seed=1),
                filename="photo.png", document_type="photo")

    response = client.post(
        f"{API}/employees/{employee['id']}/face-match", headers=hr_headers
    )
    assert response.status_code == 409
    assert "photo and an Aadhaar or PAN" in response.json()["error"]["message"]


def test_stub_matcher_reports_error_rather_than_a_fake_pass(monkeypatch):
    """A fabricated 'match' would be worse than an honest 'not configured'."""
    from app.services import face

    monkeypatch.setattr(settings, "FACE_MATCHER", "stub")
    face.get_face_matcher.cache_clear()

    result = face.compare_faces(draw_face(seed=0), draw_face(seed=0))
    assert result.outcome is FaceMatchOutcome.ERROR
    assert not result.passed
    assert "not configured" in result.message
