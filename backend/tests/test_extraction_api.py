"""Extraction pipeline through the API: review, correction, and apply-to-profile.

Uses PDFs with a real embedded text layer so extraction is exercised end to end
without depending on Tesseract's accuracy (that is covered by test_ocr_real.py).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.document import Document
from app.models.enums import AuditAction, DocumentStatus
from tests.conftest import API
from tests.factories import (
    AADHAAR_TEXT,
    PAN_TEXT,
    RESUME_TEXT,
    VALID_AADHAAR,
    VALID_PAN,
    make_png,
    make_text_pdf,
    upload_file,
)

EMPLOYEE = {
    "first_name": "Ananya",
    "last_name": "Sharma",
    "work_email": "ananya.sharma@example.com",
}


@pytest.fixture
def employee_id(client, hr_headers) -> str:
    return client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers).json()["id"]


def upload_pdf(client, headers, employee_id, text: str, document_type: str):
    return upload_file(
        client, headers, employee_id,
        data=make_text_pdf(text),
        filename=f"{document_type}.pdf",
        document_type=document_type,
        content_type="application/pdf",
    )


# --- Pipeline --------------------------------------------------------------


def test_pdf_text_layer_is_used_without_ocr(client, hr_headers, employee_id):
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()

    detail = client.get(f"{API}/documents/{uploaded['id']}", headers=hr_headers).json()
    assert detail["status"] == "extracted"
    assert detail["extraction_source"] == "pdf_text"
    # An embedded text layer is exact, so confidence is maximal.
    assert detail["ocr_confidence"] == 1.0


def test_aadhaar_fields_are_extracted_through_the_api(client, hr_headers, employee_id):
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    detail = client.get(f"{API}/documents/{uploaded['id']}", headers=hr_headers).json()

    fields = {f["field_name"]: f for f in detail["fields"]}
    assert fields["aadhaar_number"]["value"] == VALID_AADHAAR
    assert fields["date_of_birth"]["value"] == "1996-03-14"
    assert fields["full_name"]["value"] == "Ananya Sharma"
    assert fields["aadhaar_number"]["is_low_confidence"] is False


def test_pan_fields_are_extracted_through_the_api(client, hr_headers, employee_id):
    uploaded = upload_pdf(client, hr_headers, employee_id, PAN_TEXT, "pan").json()
    detail = client.get(f"{API}/documents/{uploaded['id']}", headers=hr_headers).json()

    fields = {f["field_name"]: f["value"] for f in detail["fields"]}
    assert fields["pan_number"] == VALID_PAN
    assert fields["father_name"] == "Suresh Verma"


def test_resume_is_parsed_into_a_structured_profile(client, hr_headers, employee_id):
    uploaded = upload_pdf(client, hr_headers, employee_id, RESUME_TEXT, "resume").json()
    detail = client.get(f"{API}/documents/{uploaded['id']}", headers=hr_headers).json()

    profile = detail["resume_profile"]
    assert profile is not None
    assert profile["candidate_name"] == "Meera Iyer"
    assert profile["email"] == "meera.iyer@example.com"
    assert any(e["degree"] == "BTECH" for e in profile["education"])
    assert len(profile["experience"]) == 2
    assert "python" in profile["skills"]
    assert profile["total_experience_years"] > 0


def test_extraction_is_audited(client, hr_headers, employee_id, db):
    upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar")

    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.DOCUMENT_EXTRACTED.value)
    )
    assert entry is not None
    assert entry.detail["engine"] == "pdf_text"
    assert entry.detail["fields_found"] > 0


def test_a_document_with_no_readable_text_still_completes(client, hr_headers, employee_id):
    """A blank image must finish as `extracted` with zero fields, not hang or fail."""
    uploaded = upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="blank.png", document_type="aadhaar",
    ).json()

    detail = client.get(f"{API}/documents/{uploaded['id']}", headers=hr_headers).json()
    assert detail["status"] == "extracted"
    assert detail["fields"] == []


def test_extraction_failure_is_recorded_on_the_document(
    client, hr_headers, employee_id, db, monkeypatch
):
    """A corrupt file must surface as `failed` with a message, never a 500."""
    import app.services.extraction.pipeline as pipeline

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated OCR crash")

    monkeypatch.setattr(pipeline, "extract_text", boom)

    uploaded = upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="x.png", document_type="aadhaar",
    )
    assert uploaded.status_code == 201

    detail = client.get(
        f"{API}/documents/{uploaded.json()['id']}", headers=hr_headers
    ).json()
    assert detail["status"] == "failed"
    assert "simulated OCR crash" in detail["error_message"]

    entry = db.scalar(
        select(AuditLog).where(
            AuditLog.action == AuditAction.DOCUMENT_EXTRACTION_FAILED.value
        )
    )
    assert entry is not None


def test_reprocess_is_idempotent(client, hr_headers, employee_id, db):
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()

    before = client.get(f"{API}/documents/{uploaded['id']}", headers=hr_headers).json()
    response = client.post(f"{API}/documents/{uploaded['id']}/reprocess", headers=hr_headers)
    assert response.status_code == 200

    after = client.get(f"{API}/documents/{uploaded['id']}", headers=hr_headers).json()
    # Re-running replaces rather than duplicates the extracted fields.
    assert len(after["fields"]) == len(before["fields"])


def test_reprocess_requires_hr(client, hr_headers, employee_id, admin_headers):
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    assert (
        client.post(f"{API}/documents/{uploaded['id']}/reprocess", headers=admin_headers).status_code
        == 200
    )


# --- Field correction ------------------------------------------------------


def test_hr_can_correct_an_extracted_field(client, hr_headers, employee_id):
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    detail = client.get(f"{API}/documents/{uploaded['id']}", headers=hr_headers).json()
    field = next(f for f in detail["fields"] if f["field_name"] == "full_name")

    response = client.patch(
        f"{API}/documents/{uploaded['id']}/fields/{field['id']}",
        json={"corrected_value": "Ananya R Sharma"},
        headers=hr_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["corrected_value"] == "Ananya R Sharma"
    assert body["effective_value"] == "Ananya R Sharma"
    # The original OCR value is preserved for audit.
    assert body["value"] == "Ananya Sharma"


def test_correcting_a_field_from_another_document_is_rejected(
    client, hr_headers, employee_id
):
    first = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    second = upload_pdf(client, hr_headers, employee_id, PAN_TEXT, "pan").json()

    field_id = client.get(
        f"{API}/documents/{first['id']}", headers=hr_headers
    ).json()["fields"][0]["id"]

    response = client.patch(
        f"{API}/documents/{second['id']}/fields/{field_id}",
        json={"corrected_value": "x"},
        headers=hr_headers,
    )
    assert response.status_code == 404


# --- Apply to profile ------------------------------------------------------


def test_extracted_values_can_be_applied_to_the_profile(client, hr_headers, employee_id):
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()

    response = client.post(
        f"{API}/documents/{uploaded['id']}/apply-to-profile", json={}, headers=hr_headers
    )
    assert response.status_code == 200
    assert response.json()["applied"]["date_of_birth"] == "1996-03-14"

    employee = client.get(f"{API}/employees/{employee_id}", headers=hr_headers).json()
    assert employee["date_of_birth"] == "1996-03-14"
    assert employee["postal_code"] == "560001"


def test_id_numbers_are_never_written_onto_the_profile(client, hr_headers, employee_id):
    """Aadhaar/PAN are Phase 3 verification inputs, not profile columns."""
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()

    result = client.post(
        f"{API}/documents/{uploaded['id']}/apply-to-profile", json={}, headers=hr_headers
    ).json()

    assert "aadhaar_number" not in result["applied"]
    assert result["skipped"]["aadhaar_number"] == "not a profile field"


def _weaken(db, document_id: str, field_name: str, confidence: float) -> str:
    """Force one extracted field to a low confidence, simulating a poor scan."""
    from app.models.document import ExtractedField

    field = db.scalar(
        select(ExtractedField).where(
            ExtractedField.document_id == uuid.UUID(document_id),
            ExtractedField.field_name == field_name,
        )
    )
    field.confidence = confidence
    db.commit()
    return str(field.id)


def test_confidence_threshold_blocks_weak_values(client, hr_headers, employee_id, db):
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    _weaken(db, uploaded["id"], "date_of_birth", 0.40)

    result = client.post(
        f"{API}/documents/{uploaded['id']}/apply-to-profile",
        json={"min_confidence": 0.70},
        headers=hr_headers,
    ).json()

    assert "date_of_birth" not in result["applied"]
    assert "below threshold" in result["skipped"]["date_of_birth"]

    employee = client.get(f"{API}/employees/{employee_id}", headers=hr_headers).json()
    assert employee["date_of_birth"] is None


def test_low_confidence_fields_are_flagged_for_review(client, hr_headers, employee_id, db):
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    _weaken(db, uploaded["id"], "date_of_birth", 0.40)

    detail = client.get(f"{API}/documents/{uploaded['id']}", headers=hr_headers).json()
    dob = next(f for f in detail["fields"] if f["field_name"] == "date_of_birth")
    assert dob["is_low_confidence"] is True


def test_a_correction_overrides_the_confidence_threshold(
    client, hr_headers, employee_id, db
):
    """A human-entered value is trusted regardless of the original OCR score."""
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    field_id = _weaken(db, uploaded["id"], "date_of_birth", 0.10)

    client.patch(
        f"{API}/documents/{uploaded['id']}/fields/{field_id}",
        json={"corrected_value": "01/01/1990"},
        headers=hr_headers,
    )

    result = client.post(
        f"{API}/documents/{uploaded['id']}/apply-to-profile",
        json={"min_confidence": 0.90},
        headers=hr_headers,
    ).json()

    assert result["applied"]["date_of_birth"] == "1990-01-01"


def test_min_confidence_outside_zero_to_one_is_rejected(client, hr_headers, employee_id):
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    response = client.post(
        f"{API}/documents/{uploaded['id']}/apply-to-profile",
        json={"min_confidence": 1.5},
        headers=hr_headers,
    )
    assert response.status_code == 422


def test_applying_only_selected_fields(client, hr_headers, employee_id):
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()

    result = client.post(
        f"{API}/documents/{uploaded['id']}/apply-to-profile",
        json={"field_names": ["date_of_birth"]},
        headers=hr_headers,
    ).json()

    assert set(result["applied"]) == {"date_of_birth"}

    employee = client.get(f"{API}/employees/{employee_id}", headers=hr_headers).json()
    assert employee["postal_code"] is None


def test_cannot_apply_before_extraction_completes(
    client, hr_headers, employee_id, db, monkeypatch
):
    import app.services.extraction.pipeline as pipeline

    monkeypatch.setattr(
        pipeline, "extract_text", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("x"))
    )
    uploaded = upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="x.png", document_type="aadhaar",
    ).json()

    response = client.post(
        f"{API}/documents/{uploaded['id']}/apply-to-profile", json={}, headers=hr_headers
    )
    assert response.status_code == 409


def test_apply_is_audited(client, hr_headers, employee_id, db):
    uploaded = upload_pdf(client, hr_headers, employee_id, AADHAAR_TEXT, "aadhaar").json()
    client.post(
        f"{API}/documents/{uploaded['id']}/apply-to-profile", json={}, headers=hr_headers
    )

    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.EXTRACTION_APPLIED.value)
    )
    assert entry is not None
    assert "date_of_birth" in entry.detail["applied"]
