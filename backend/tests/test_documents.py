"""Document upload, validation, storage, RBAC, and download."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.audit import AuditLog
from app.models.document import Document
from app.models.enums import AuditAction
from tests.conftest import API
from tests.factories import (
    AADHAAR_TEXT,
    RESUME_TEXT,
    make_jpeg,
    make_png,
    make_scanned_pdf,
    make_text_image,
    make_text_pdf,
    upload_file,
)

EMPLOYEE = {
    "first_name": "Ananya",
    "last_name": "Sharma",
    "work_email": "ananya.sharma@example.com",
    "department": "Engineering",
}


@pytest.fixture
def employee_id(client, hr_headers) -> str:
    response = client.post(f"{API}/employees", json=EMPLOYEE, headers=hr_headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.fixture
def registered_employee(client, hr_headers):
    """An employee who has activated their account, plus their auth headers."""
    import re
    from pathlib import Path

    created = client.post(
        f"{API}/employees",
        json={**EMPLOYEE, "work_email": "meera.iyer@example.com", "first_name": "Meera",
              "last_name": "Iyer"},
        headers=hr_headers,
    )
    employee_id = created.json()["id"]

    files = sorted(Path(settings.EMAIL_OUTBOX_DIR).glob("*.txt"))
    token = re.search(r"accept-invite\?token=([A-Za-z0-9_\-]+)", files[-1].read_text()).group(1)
    client.post(
        f"{API}/onboarding/accept", json={"token": token, "password": "Meera@12345"}
    )

    tokens = client.post(
        f"{API}/auth/login",
        json={"email": "meera.iyer@example.com", "password": "Meera@12345"},
    ).json()
    return employee_id, {"Authorization": f"Bearer {tokens['access_token']}"}


# --- Upload ----------------------------------------------------------------


def test_hr_can_upload_a_document(client, hr_headers, employee_id):
    response = upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="aadhaar.png", document_type="aadhaar",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document_type"] == "aadhaar"
    assert body["content_type"] == "image/png"
    assert body["size_bytes"] > 0
    assert len(body["checksum_sha256"]) == 64


def test_upload_persists_the_file_to_storage(client, hr_headers, employee_id, db):
    upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="aadhaar.png", document_type="aadhaar",
    )
    from app.services.storage import get_storage

    document = db.scalar(select(Document))
    assert get_storage().exists(document.storage_key)


def test_upload_is_audited(client, hr_headers, employee_id, db):
    upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="aadhaar.png", document_type="aadhaar",
    )
    entry = db.scalar(
        select(AuditLog).where(AuditLog.action == AuditAction.DOCUMENT_UPLOADED.value)
    )
    assert entry is not None
    assert entry.detail["document_type"] == "aadhaar"


# --- Validation ------------------------------------------------------------


def test_disguised_executable_is_rejected(client, hr_headers, employee_id):
    """A real attack shape: an executable renamed .png with an image mime type."""
    response = upload_file(
        client, hr_headers, employee_id,
        data=b"MZ\x90\x00\x03" + b"\x00" * 500,
        filename="payload.png", document_type="aadhaar", content_type="image/png",
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_content_type_mismatch_is_rejected(client, hr_headers, employee_id):
    """Real PNG bytes declared as a PDF — the mismatch is surfaced, not ignored."""
    response = upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="doc.pdf", document_type="aadhaar",
        content_type="application/pdf",
    )
    assert response.status_code == 422


def test_oversized_file_is_rejected(client, hr_headers, employee_id, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_MB", 0.001)
    response = upload_file(
        client, hr_headers, employee_id,
        data=make_png(800, 800), filename="big.png", document_type="aadhaar",
    )
    assert response.status_code == 422
    assert "too large" in response.json()["error"]["message"].lower()


def test_empty_file_is_rejected(client, hr_headers, employee_id):
    response = upload_file(
        client, hr_headers, employee_id,
        data=b"", filename="empty.png", document_type="aadhaar",
    )
    assert response.status_code == 422


def test_photo_must_be_an_image_not_a_pdf(client, hr_headers, employee_id):
    response = upload_file(
        client, hr_headers, employee_id,
        data=make_text_pdf("hello"), filename="me.pdf", document_type="photo",
        content_type="application/pdf",
    )
    assert response.status_code == 422
    assert "photo" in response.json()["error"]["message"].lower()


def test_jpeg_and_pdf_are_accepted(client, hr_headers, employee_id):
    jpeg = upload_file(
        client, hr_headers, employee_id,
        data=make_jpeg(), filename="scan.jpg", document_type="pan",
        content_type="image/jpeg",
    )
    assert jpeg.status_code == 201
    assert jpeg.json()["content_type"] == "image/jpeg"

    pdf = upload_file(
        client, hr_headers, employee_id,
        data=make_text_pdf("Certificate of completion"), filename="cert.pdf",
        document_type="certificate", content_type="application/pdf",
    )
    assert pdf.status_code == 201
    assert pdf.json()["content_type"] == "application/pdf"


def test_path_traversal_filename_is_neutralised(client, hr_headers, employee_id, db):
    response = upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="../../../../etc/passwd.png", document_type="aadhaar",
    )
    assert response.status_code == 201
    assert response.json()["original_filename"] == "passwd.png"

    document = db.scalar(select(Document))
    assert ".." not in document.storage_key
    assert document.storage_key.startswith("employees/")


def test_unknown_document_type_is_rejected(client, hr_headers, employee_id):
    response = upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="x.png", document_type="passport",
    )
    assert response.status_code == 422


# --- RBAC ------------------------------------------------------------------


def test_upload_requires_authentication(client, employee_id):
    response = client.post(
        f"{API}/employees/{employee_id}/documents",
        files={"file": ("a.png", make_png(), "image/png")},
        data={"document_type": "aadhaar"},
    )
    assert response.status_code == 401


def test_employee_can_upload_to_their_own_record(client, registered_employee):
    employee_id, headers = registered_employee
    response = upload_file(
        client, headers, employee_id,
        data=make_png(), filename="mine.png", document_type="aadhaar",
    )
    assert response.status_code == 201


def test_employee_cannot_upload_to_someone_else(client, registered_employee, employee_id):
    _, headers = registered_employee
    response = upload_file(
        client, headers, employee_id,
        data=make_png(), filename="theirs.png", document_type="aadhaar",
    )
    assert response.status_code == 403


def test_employee_cannot_read_another_employees_document(
    client, hr_headers, registered_employee, employee_id
):
    _, headers = registered_employee
    uploaded = upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="theirs.png", document_type="aadhaar",
    ).json()

    assert client.get(f"{API}/documents/{uploaded['id']}", headers=headers).status_code == 403
    assert (
        client.get(f"{API}/employees/{employee_id}/documents", headers=headers).status_code
        == 403
    )


# --- Listing & retrieval ---------------------------------------------------


def test_documents_can_be_listed_and_filtered(client, hr_headers, employee_id):
    upload_file(client, hr_headers, employee_id, data=make_png(),
                filename="a.png", document_type="aadhaar")
    upload_file(client, hr_headers, employee_id, data=make_png(),
                filename="p.png", document_type="pan")

    everything = client.get(f"{API}/employees/{employee_id}/documents", headers=hr_headers)
    assert len(everything.json()) == 2

    only_pan = client.get(
        f"{API}/employees/{employee_id}/documents?document_type=pan", headers=hr_headers
    )
    assert len(only_pan.json()) == 1
    assert only_pan.json()[0]["document_type"] == "pan"


def test_unknown_document_returns_404(client, hr_headers):
    response = client.get(
        f"{API}/documents/00000000-0000-0000-0000-000000000000", headers=hr_headers
    )
    assert response.status_code == 404


# --- Download --------------------------------------------------------------


def test_signed_download_link_round_trip(client, hr_headers, employee_id):
    payload = make_png()
    uploaded = upload_file(
        client, hr_headers, employee_id,
        data=payload, filename="a.png", document_type="aadhaar",
    ).json()

    link = client.get(f"{API}/documents/{uploaded['id']}/download-url", headers=hr_headers)
    assert link.status_code == 200
    url = link.json()["url"]

    # The signed token alone authorises the download — no Authorization header.
    downloaded = client.get(url)
    assert downloaded.status_code == 200
    assert downloaded.content == payload
    assert downloaded.headers["content-type"] == "image/png"


def test_download_rejects_a_tampered_token(client, hr_headers, employee_id):
    uploaded = upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="a.png", document_type="aadhaar",
    ).json()

    url = client.get(
        f"{API}/documents/{uploaded['id']}/download-url", headers=hr_headers
    ).json()["url"]

    assert client.get(url + "tampered").status_code == 403
    assert client.get(url.replace("token=", "token=x")).status_code == 403


def test_download_token_expires(client, hr_headers, employee_id, monkeypatch):
    uploaded = upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="a.png", document_type="aadhaar",
    ).json()

    monkeypatch.setattr(settings, "DOWNLOAD_URL_EXPIRE_SECONDS", -1)
    url = client.get(
        f"{API}/documents/{uploaded['id']}/download-url", headers=hr_headers
    ).json()["url"]

    assert client.get(url).status_code == 403


def test_download_token_is_bound_to_one_document(client, hr_headers, employee_id):
    first = upload_file(client, hr_headers, employee_id, data=make_png(),
                        filename="a.png", document_type="aadhaar").json()
    second = upload_file(client, hr_headers, employee_id, data=make_png(),
                         filename="b.png", document_type="pan").json()

    token = client.get(
        f"{API}/documents/{first['id']}/download-url", headers=hr_headers
    ).json()["url"].split("token=")[1]

    # Reusing the first document's token against the second must fail.
    response = client.get(f"{API}/documents/{second['id']}/download?token={token}")
    assert response.status_code == 403


# --- Deletion --------------------------------------------------------------


def test_delete_removes_the_row_and_the_stored_file(client, hr_headers, employee_id, db):
    uploaded = upload_file(
        client, hr_headers, employee_id,
        data=make_png(), filename="a.png", document_type="aadhaar",
    ).json()

    from app.services.storage import get_storage

    document = db.scalar(select(Document))
    key = document.storage_key
    assert get_storage().exists(key)

    response = client.delete(f"{API}/documents/{uploaded['id']}", headers=hr_headers)
    assert response.status_code == 200
    assert not get_storage().exists(key)
    assert client.get(f"{API}/documents/{uploaded['id']}", headers=hr_headers).status_code == 404


def test_deleting_an_employee_cascades_to_documents(
    client, hr_headers, admin_headers, employee_id, db
):
    upload_file(client, hr_headers, employee_id, data=make_png(),
                filename="a.png", document_type="aadhaar")
    assert db.scalar(select(Document)) is not None

    client.delete(f"{API}/employees/{employee_id}", headers=admin_headers)
    db.expire_all()
    assert db.scalar(select(Document)) is None
