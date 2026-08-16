"""Mock Aadhaar/PAN verification (PRD A.7.4 / B.4.4).

This simulates a UIDAI/NSDL-style check. **No government API is contacted** —
live integration is explicitly out of scope for v1 (PRD A.4.2). Every result is
labelled with the mock provider so a mock pass can never be mistaken for a real
identity verification.

Outcomes are deterministic, derived from the ID number itself, so demos and
tests reproduce exactly:

  * format and checksum are validated (Verhoeff for Aadhaar, grammar for PAN);
  * numbers in the reserved test ranges always fail, for exercising the reject
    path on demand;
  * anything else that is structurally valid passes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum

from app.core.config import settings
from app.services.extraction.fields import is_valid_aadhaar, is_valid_pan


class VerificationOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class VerificationReason(str, Enum):
    """Machine-readable reason codes, mirroring a real provider's response."""

    VERIFIED = "verified"
    MISSING_NUMBER = "missing_number"
    INVALID_FORMAT = "invalid_format"
    CHECKSUM_FAILED = "checksum_failed"
    NOT_FOUND_IN_REGISTRY = "not_found_in_registry"
    NAME_MISMATCH = "name_mismatch"
    DOB_MISMATCH = "dob_mismatch"


# Numbers reserved for exercising the failure path in demos and tests.
# Structurally valid, so they reach the simulated registry lookup and are
# rejected there rather than failing format validation.
RESERVED_FAILING_AADHAAR = {"999999990019"}
RESERVED_FAILING_PAN = {"AAAPZ9999Z"}


@dataclass
class VerificationResult:
    outcome: VerificationOutcome
    reason: VerificationReason
    message: str
    provider: str = settings.MOCK_VERIFICATION_PROVIDER
    reference_id: str | None = None
    masked_number: str | None = None
    registry_name: str | None = None
    name_similarity: float | None = None
    detail: dict = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.outcome is VerificationOutcome.PASSED

    def as_dict(self) -> dict:
        return {
            "outcome": self.outcome.value,
            "reason": self.reason.value,
            "message": self.message,
            "provider": self.provider,
            "reference_id": self.reference_id,
            "masked_number": self.masked_number,
            "registry_name": self.registry_name,
            "name_similarity": self.name_similarity,
            "is_mock": True,
            **self.detail,
        }


# --- Helpers ---------------------------------------------------------------


def mask_aadhaar(number: str) -> str:
    """Show only the last four digits — the full number is never persisted."""
    digits = re.sub(r"\D", "", number or "")
    return f"XXXX XXXX {digits[-4:]}" if len(digits) >= 4 else "XXXX"


def mask_pan(pan: str) -> str:
    pan = (pan or "").strip().upper()
    return f"{pan[:2]}XXXXX{pan[-1]}" if len(pan) == 10 else "XXXXXXXXXX"


def make_reference_id(check_type: str, number: str) -> str:
    """Stable pseudo-reference, as a real provider would return."""
    digest = hashlib.sha256(f"{check_type}:{number}".encode()).hexdigest()[:12].upper()
    return f"MOCK-{check_type.upper()}-{digest}"


def name_similarity(left: str | None, right: str | None) -> float | None:
    """Order-insensitive name comparison tolerant of initials and extra names."""
    if not left or not right:
        return None

    def normalise(value: str) -> list[str]:
        cleaned = re.sub(r"[^a-z\s]", " ", value.lower())
        return sorted(part for part in cleaned.split() if len(part) > 1)

    left_parts, right_parts = normalise(left), normalise(right)
    if not left_parts or not right_parts:
        return None

    # Token overlap handles reordering; sequence ratio catches spelling drift.
    overlap = len(set(left_parts) & set(right_parts)) / max(
        len(set(left_parts)), len(set(right_parts))
    )
    ratio = SequenceMatcher(None, " ".join(left_parts), " ".join(right_parts)).ratio()
    return round(max(overlap, ratio), 4)


# --- Verification ----------------------------------------------------------


def verify_aadhaar(number: str | None, *, expected_name: str | None = None) -> VerificationResult:
    if not number or not number.strip():
        return VerificationResult(
            outcome=VerificationOutcome.FAILED,
            reason=VerificationReason.MISSING_NUMBER,
            message="No Aadhaar number could be read from the document.",
        )

    digits = re.sub(r"\D", "", number)
    masked = mask_aadhaar(digits)

    if len(digits) != 12:
        return VerificationResult(
            outcome=VerificationOutcome.FAILED,
            reason=VerificationReason.INVALID_FORMAT,
            message=f"An Aadhaar number must be 12 digits; got {len(digits)}.",
            masked_number=masked,
        )

    if not is_valid_aadhaar(digits):
        return VerificationResult(
            outcome=VerificationOutcome.FAILED,
            reason=VerificationReason.CHECKSUM_FAILED,
            message=(
                "The Aadhaar number failed its checksum, which usually means a "
                "digit was misread. Check the scan quality and correct the value."
            ),
            masked_number=masked,
        )

    reference = make_reference_id("aadhaar", digits)

    if digits in RESERVED_FAILING_AADHAAR:
        return VerificationResult(
            outcome=VerificationOutcome.FAILED,
            reason=VerificationReason.NOT_FOUND_IN_REGISTRY,
            message="This Aadhaar number was not found in the (simulated) registry.",
            reference_id=reference,
            masked_number=masked,
        )

    # The simulated registry echoes the name on the document, so the comparison
    # exercises the real code path HR will rely on once a live API is wired in.
    similarity = name_similarity(expected_name, expected_name)
    return VerificationResult(
        outcome=VerificationOutcome.PASSED,
        reason=VerificationReason.VERIFIED,
        message="Aadhaar verified against the simulated registry.",
        reference_id=reference,
        masked_number=masked,
        registry_name=expected_name,
        name_similarity=similarity,
    )


def verify_pan(pan: str | None, *, expected_name: str | None = None) -> VerificationResult:
    if not pan or not pan.strip():
        return VerificationResult(
            outcome=VerificationOutcome.FAILED,
            reason=VerificationReason.MISSING_NUMBER,
            message="No PAN could be read from the document.",
        )

    value = pan.strip().upper()
    masked = mask_pan(value)

    if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", value):
        return VerificationResult(
            outcome=VerificationOutcome.FAILED,
            reason=VerificationReason.INVALID_FORMAT,
            message="A PAN must be five letters, four digits, then one letter.",
            masked_number=masked,
        )

    if not is_valid_pan(value):
        return VerificationResult(
            outcome=VerificationOutcome.FAILED,
            reason=VerificationReason.INVALID_FORMAT,
            message=(
                "The PAN's fourth character is not a recognised holder-type code, "
                "so the number is not structurally valid."
            ),
            masked_number=masked,
        )

    reference = make_reference_id("pan", value)

    if value in RESERVED_FAILING_PAN:
        return VerificationResult(
            outcome=VerificationOutcome.FAILED,
            reason=VerificationReason.NOT_FOUND_IN_REGISTRY,
            message="This PAN was not found in the (simulated) registry.",
            reference_id=reference,
            masked_number=masked,
        )

    return VerificationResult(
        outcome=VerificationOutcome.PASSED,
        reason=VerificationReason.VERIFIED,
        message="PAN verified against the simulated registry.",
        reference_id=reference,
        masked_number=masked,
        registry_name=expected_name,
        name_similarity=name_similarity(expected_name, expected_name),
    )


def check_name_against_profile(
    document_name: str | None, profile_name: str | None
) -> tuple[float | None, bool]:
    """Compare the name on the ID with the employee profile.

    Returns (similarity, is_match). A None similarity means one side was
    missing, which is reported as "not checked" rather than a mismatch.
    """
    similarity = name_similarity(document_name, profile_name)
    if similarity is None:
        return None, True
    return similarity, similarity >= settings.NAME_MATCH_THRESHOLD


VERIFIERS = {
    "aadhaar": verify_aadhaar,
    "pan": verify_pan,
}


def verify_id_number(
    check_type: str, number: str | None, *, expected_name: str | None = None
) -> VerificationResult:
    verifier = VERIFIERS.get(check_type)
    if verifier is None:
        return VerificationResult(
            outcome=VerificationOutcome.ERROR,
            reason=VerificationReason.INVALID_FORMAT,
            message=f"No verifier is configured for document type '{check_type}'.",
        )
    return verifier(number, expected_name=expected_name)
