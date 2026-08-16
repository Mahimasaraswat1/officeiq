"""Real OCR accuracy tests against a live Tesseract install.

Skipped automatically when Tesseract is absent, so CI stays green on machines
without it. These are the PRD B.7 "OCR accuracy tests against a labelled sample
set" — the labels are the known strings rendered into each generated image.
"""

from __future__ import annotations

import os

import pytest

from app.services.extraction.fields import extract_aadhaar_fields, extract_pan_fields
from app.services.extraction.resume import RuleBasedResumeParser
from app.services.ocr import extract_text
from tests.factories import (
    AADHAAR_TEXT,
    PAN_TEXT,
    RESUME_TEXT,
    VALID_AADHAAR,
    VALID_PAN,
    make_scanned_pdf,
    make_text_image,
)


def _tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _tesseract_available(), reason="Tesseract is not installed on this host"
)


@pytest.fixture(autouse=True)
def _use_real_tesseract(monkeypatch):
    """Point the engine factory at Tesseract regardless of the CI default."""
    from app.core.config import settings
    from app.services import ocr

    monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")
    ocr.get_ocr_engine.cache_clear()
    yield
    ocr.get_ocr_engine.cache_clear()


def test_tesseract_engine_is_selected_and_available():
    from app.services.ocr import get_ocr_engine

    engine = get_ocr_engine()
    assert engine.name == "tesseract"
    assert engine.is_available()


def test_ocr_reads_text_from_a_rendered_image():
    result = extract_text(make_text_image("HELLO OFFICEIQ 12345"), "image/png")

    assert "OFFICEIQ" in result.text.upper()
    assert result.engine == "tesseract"
    assert 0.0 < result.mean_confidence <= 1.0


def test_ocr_preserves_line_structure():
    """Line breaks must survive OCR.

    Regression: rebuilding the text by joining every word with a space made the
    whole document one line, so "Name: Ananya Sharma" ran into the following
    "DOB:" label and the extracted name became "Ananya Sharma Dob".
    """
    result = extract_text(make_text_image(AADHAAR_TEXT), "image/png")

    assert "\n" in result.text
    lines = [line.strip() for line in result.text.splitlines() if line.strip()]
    assert len(lines) >= 5

    name_line = next(line for line in lines if "Name" in line)
    assert "DOB" not in name_line.upper()


def test_ocr_extracted_name_does_not_bleed_into_the_next_label():
    result = extract_text(make_text_image(AADHAAR_TEXT), "image/png")
    fields = {f.field_name: f.value for f in extract_aadhaar_fields(result)}

    assert fields.get("full_name") == "Ananya Sharma", f"OCR text: {result.text!r}"


def test_ocr_extracts_aadhaar_number_from_a_rendered_card():
    result = extract_text(make_text_image(AADHAAR_TEXT), "image/png")
    fields = {f.field_name: f for f in extract_aadhaar_fields(result)}

    assert "aadhaar_number" in fields, f"OCR text was: {result.text!r}"
    assert fields["aadhaar_number"].value == VALID_AADHAAR
    # A checksum-valid read off a clean render should clear the review threshold.
    assert fields["aadhaar_number"].confidence >= 0.70


def test_ocr_extracts_pan_from_a_rendered_card():
    result = extract_text(make_text_image(PAN_TEXT), "image/png")
    fields = {f.field_name: f for f in extract_pan_fields(result)}

    assert "pan_number" in fields, f"OCR text was: {result.text!r}"
    assert fields["pan_number"].value == VALID_PAN


def test_ocr_extracts_date_of_birth():
    result = extract_text(make_text_image(AADHAAR_TEXT), "image/png")
    fields = {f.field_name: f.value for f in extract_aadhaar_fields(result)}

    assert fields.get("date_of_birth") == "1996-03-14", f"OCR text: {result.text!r}"


def test_scanned_pdf_falls_back_to_ocr():
    """A PDF with no text layer must be rasterised and OCR'd, not skipped."""
    result = extract_text(make_scanned_pdf(AADHAAR_TEXT), "application/pdf")

    assert result.engine == "tesseract"
    assert result.text.strip()
    assert "SHARMA" in result.text.upper()


def test_resume_parsed_from_a_scanned_image():
    result = extract_text(make_text_image(RESUME_TEXT, height=900), "image/png")
    parsed = RuleBasedResumeParser().parse(result)

    assert parsed.email == "meera.iyer@example.com", f"OCR text: {result.text!r}"
    assert parsed.skills


def test_blank_image_yields_no_text_without_crashing():
    from tests.factories import make_png

    result = extract_text(make_png(), "image/png")
    assert result.text.strip() == ""
    assert result.mean_confidence == 0.0


def test_full_upload_pipeline_with_real_ocr(client, hr_headers, monkeypatch):
    """End-to-end: upload a rendered Aadhaar PNG and read the extracted fields."""
    from app.core.config import settings
    from tests.conftest import API
    from tests.factories import upload_file

    monkeypatch.setattr(settings, "OCR_ENGINE", "tesseract")

    employee = client.post(
        f"{API}/employees",
        json={
            "first_name": "Ananya",
            "last_name": "Sharma",
            "work_email": "ocr.test@example.com",
        },
        headers=hr_headers,
    ).json()

    uploaded = upload_file(
        client, hr_headers, employee["id"],
        data=make_text_image(AADHAAR_TEXT),
        filename="aadhaar.png",
        document_type="aadhaar",
    )
    assert uploaded.status_code == 201

    detail = client.get(f"{API}/documents/{uploaded.json()['id']}", headers=hr_headers).json()
    assert detail["status"] == "extracted"
    assert detail["extraction_source"] == "ocr"
    assert detail["ocr_confidence"] > 0

    fields = {f["field_name"]: f["value"] for f in detail["fields"]}
    assert fields.get("aadhaar_number") == VALID_AADHAAR, f"got fields: {fields}"
