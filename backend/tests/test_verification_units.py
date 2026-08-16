"""Unit tests for the mock ID verification service and name matching."""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.verification import (
    RESERVED_FAILING_AADHAAR,
    RESERVED_FAILING_PAN,
    VerificationOutcome,
    VerificationReason,
    check_name_against_profile,
    make_reference_id,
    mask_aadhaar,
    mask_pan,
    name_similarity,
    verify_aadhaar,
    verify_id_number,
    verify_pan,
)
from tests.factories import VALID_AADHAAR, VALID_PAN


# --- Masking ---------------------------------------------------------------


def test_aadhaar_is_masked_to_the_last_four_digits():
    masked = mask_aadhaar(VALID_AADHAAR)
    assert masked == "XXXX XXXX 2346"
    # The full number must never appear in the masked form.
    assert VALID_AADHAAR not in masked


def test_pan_is_masked():
    masked = mask_pan(VALID_PAN)
    assert masked.startswith("AB")
    assert masked.endswith("E")
    assert VALID_PAN not in masked


def test_masking_handles_short_or_missing_input():
    assert mask_aadhaar("") == "XXXX"
    assert mask_pan("") == "XXXXXXXXXX"
    assert mask_pan("SHORT") == "XXXXXXXXXX"


# --- Reference ids ---------------------------------------------------------


def test_reference_id_is_deterministic_and_labelled_mock():
    first = make_reference_id("aadhaar", VALID_AADHAAR)
    second = make_reference_id("aadhaar", VALID_AADHAAR)

    assert first == second
    assert first.startswith("MOCK-AADHAAR-")
    # The reference must not leak the underlying number.
    assert VALID_AADHAAR not in first


def test_reference_ids_differ_per_number():
    assert make_reference_id("aadhaar", VALID_AADHAAR) != make_reference_id(
        "aadhaar", "234123412353"
    )


# --- Aadhaar verification --------------------------------------------------


def test_valid_aadhaar_passes():
    result = verify_aadhaar(VALID_AADHAAR, expected_name="Ananya Sharma")

    assert result.outcome is VerificationOutcome.PASSED
    assert result.reason is VerificationReason.VERIFIED
    assert result.passed
    assert result.reference_id.startswith("MOCK-")
    # Every result must be identifiable as mock, never as a real verification.
    assert result.as_dict()["is_mock"] is True


def test_spaced_aadhaar_is_accepted():
    assert verify_aadhaar("2341 2341 2346").outcome is VerificationOutcome.PASSED


def test_missing_aadhaar_fails_with_a_clear_reason():
    for value in (None, "", "   "):
        result = verify_aadhaar(value)
        assert result.outcome is VerificationOutcome.FAILED
        assert result.reason is VerificationReason.MISSING_NUMBER


def test_wrong_length_aadhaar_is_a_format_failure():
    result = verify_aadhaar("2341234")
    assert result.reason is VerificationReason.INVALID_FORMAT


def test_checksum_failure_is_reported_distinctly():
    """A misread digit must be reported as a checksum failure, not 'not found'."""
    result = verify_aadhaar("234123412345")
    assert result.outcome is VerificationOutcome.FAILED
    assert result.reason is VerificationReason.CHECKSUM_FAILED
    assert "checksum" in result.message.lower()


def test_reserved_number_always_fails_registry_lookup():
    number = next(iter(RESERVED_FAILING_AADHAAR))
    result = verify_aadhaar(number)

    assert result.outcome is VerificationOutcome.FAILED
    assert result.reason is VerificationReason.NOT_FOUND_IN_REGISTRY
    # It gets far enough to receive a reference id, like a real rejected lookup.
    assert result.reference_id is not None


def test_aadhaar_verification_is_deterministic():
    first = verify_aadhaar(VALID_AADHAAR)
    second = verify_aadhaar(VALID_AADHAAR)
    assert (first.outcome, first.reference_id) == (second.outcome, second.reference_id)


# --- PAN verification ------------------------------------------------------


def test_valid_pan_passes():
    result = verify_pan(VALID_PAN, expected_name="Rohit Verma")
    assert result.outcome is VerificationOutcome.PASSED
    assert result.reference_id.startswith("MOCK-PAN-")


def test_lowercase_pan_is_normalised():
    assert verify_pan(VALID_PAN.lower()).outcome is VerificationOutcome.PASSED


def test_malformed_pan_fails():
    for value in ("ABCD1234E", "12345ABCDE", "ABCPD12345"):
        assert verify_pan(value).outcome is VerificationOutcome.FAILED


def test_pan_with_invalid_entity_code_fails():
    """The 4th character encodes holder type; 'X' is not a valid code."""
    result = verify_pan("ABCXD1234E")
    assert result.outcome is VerificationOutcome.FAILED
    assert result.reason is VerificationReason.INVALID_FORMAT


def test_reserved_pan_fails_registry_lookup():
    result = verify_pan(next(iter(RESERVED_FAILING_PAN)))
    assert result.reason is VerificationReason.NOT_FOUND_IN_REGISTRY


def test_missing_pan_fails():
    assert verify_pan(None).reason is VerificationReason.MISSING_NUMBER


# --- Dispatch --------------------------------------------------------------


def test_verify_id_number_dispatches_by_type():
    assert verify_id_number("aadhaar", VALID_AADHAAR).passed
    assert verify_id_number("pan", VALID_PAN).passed


def test_unknown_check_type_returns_error():
    result = verify_id_number("passport", "X1234567")
    assert result.outcome is VerificationOutcome.ERROR


# --- Name matching ---------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Ananya Sharma", "Ananya Sharma"),
        ("Ananya Sharma", "ANANYA SHARMA"),
        ("Ananya Sharma", "Sharma Ananya"),      # reordered
        ("Ananya  Sharma", "Ananya Sharma"),     # extra whitespace
        ("Ananya Sharma", "Ananya R. Sharma"),   # added middle initial
    ],
)
def test_equivalent_names_score_as_a_match(left, right):
    similarity, matched = check_name_against_profile(left, right)
    assert matched, f"{left!r} vs {right!r} scored {similarity}"


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Ananya Sharma", "Rohit Verma"),
        ("Ananya Sharma", "Meera Iyer"),
    ],
)
def test_different_names_do_not_match(left, right):
    _, matched = check_name_against_profile(left, right)
    assert not matched


def test_missing_name_is_reported_as_not_checked_rather_than_mismatch():
    similarity, matched = check_name_against_profile(None, "Ananya Sharma")
    assert similarity is None
    assert matched is True  # absence of data must not be treated as a failure


def test_name_similarity_is_bounded():
    score = name_similarity("Ananya Sharma", "Ananya Sharma")
    assert 0.0 <= score <= 1.0
    assert score == 1.0
