"""Upload validation (PRD B.6: "never trust client-supplied data, especially file uploads").

The declared Content-Type and filename are both attacker-controlled, so the
real file type is determined by inspecting magic bytes.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.core.errors import ValidationError

PDF = "application/pdf"
JPEG = "image/jpeg"
PNG = "image/png"

ALLOWED_CONTENT_TYPES = {PDF, JPEG, PNG}

# Image-only document types — a PDF ID card scan is fine, but a "photo" must be
# an actual image so face matching in Phase 3 can consume it directly.
IMAGE_ONLY_TYPES = {"photo"}

EXTENSIONS = {PDF: ".pdf", JPEG: ".jpg", PNG: ".png"}


@dataclass(frozen=True)
class ValidatedUpload:
    content_type: str
    size_bytes: int


def sniff_content_type(data: bytes) -> str | None:
    """Identify the file from its magic bytes, ignoring what the client claimed."""
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"\xff\xd8\xff"):
        return JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return PNG
    return None


def validate_upload(
    *, data: bytes, filename: str, document_type: str, declared_type: str | None = None
) -> ValidatedUpload:
    """Validate size and true file type, returning the trustworthy content type."""
    if not data:
        raise ValidationError("The uploaded file is empty.")

    if len(data) > settings.max_upload_size_bytes:
        raise ValidationError(
            f"File is too large. The maximum upload size is "
            f"{settings.MAX_UPLOAD_SIZE_MB} MB."
        )

    actual = sniff_content_type(data)
    if actual is None:
        raise ValidationError(
            "Unsupported file type. Upload a PDF, JPEG, or PNG file."
        )

    # A mismatch is worth surfacing rather than silently accepting.
    if declared_type and declared_type.lower() not in (actual, "application/octet-stream"):
        raise ValidationError(
            f"File content does not match its declared type "
            f"({declared_type} vs detected {actual})."
        )

    if document_type in IMAGE_ONLY_TYPES and actual == PDF:
        raise ValidationError(
            "A photo must be a JPEG or PNG image, not a PDF."
        )

    if not filename or not filename.strip():
        raise ValidationError("A filename is required.")

    return ValidatedUpload(content_type=actual, size_bytes=len(data))


def safe_display_filename(filename: str) -> str:
    """Strip any path components — the name is for display only, never a path."""
    cleaned = filename.replace("\\", "/").split("/")[-1].strip()
    return (cleaned or "upload")[:255]
