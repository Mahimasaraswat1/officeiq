"""Unit tests for validators, field extractors, and the resume parser.

These run without a database or OCR engine — they operate on OcrResult objects
directly, so extraction logic is pinned independently of Tesseract's accuracy.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.extraction.fields import (
    extract_aadhaar_fields,
    extract_fields,
    extract_pan_fields,
    is_valid_aadhaar,
    is_valid_pan,
    parse_date,
)
from app.services.extraction.resume import RuleBasedResumeParser, split_sections
from app.services.ocr.base import OcrResult, OcrWord
from tests.factories import AADHAAR_TEXT, PAN_TEXT, RESUME_TEXT, VALID_AADHAAR, VALID_PAN


def result_from(text: str, confidence: float = 0.9) -> OcrResult:
    words = [OcrWord(text=t, confidence=confidence) for t in text.split()]
    return OcrResult(text=text, words=words, engine="test")


# --- Aadhaar validation ----------------------------------------------------


def test_verhoeff_accepts_a_valid_aadhaar():
    assert is_valid_aadhaar(VALID_AADHAAR)
    assert is_valid_aadhaar(f"{VALID_AADHAAR[:4]} {VALID_AADHAAR[4:8]} {VALID_AADHAAR[8:]}")


@pytest.mark.parametrize(
    "number",
    [
        "234123412345",  # wrong check digit
        "123412341234",  # starts with 1
        "01234123412",   # starts with 0 and too short
        "23412341234",   # 11 digits
        "2341234123467", # 13 digits
        "abcdefghijkl",
        "",
    ],
)
def test_verhoeff_rejects_invalid_aadhaar(number):
    assert not is_valid_aadhaar(number)


def test_single_digit_error_is_caught_by_the_checksum():
    """The point of Verhoeff: an OCR digit misread should not validate."""
    digits = list(VALID_AADHAAR)
    digits[5] = "9" if digits[5] != "9" else "8"
    assert not is_valid_aadhaar("".join(digits))


# --- PAN validation --------------------------------------------------------


def test_valid_pan_is_accepted():
    assert is_valid_pan(VALID_PAN)
    assert is_valid_pan(VALID_PAN.lower())


@pytest.mark.parametrize(
    "pan",
    [
        "ABCD1234E",     # too short
        "ABCPD12345",    # missing trailing letter
        "ABCXD1234E",    # invalid 4th-character entity code
        "12345678AB",
        "",
    ],
)
def test_invalid_pan_is_rejected(pan):
    assert not is_valid_pan(pan)


# --- Date parsing ----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("14/03/1996", date(1996, 3, 14)),
        ("02-11-1993", date(1993, 11, 2)),
        ("25.12.1988", date(1988, 12, 25)),
        ("1996-03-14", date(1996, 3, 14)),
    ],
)
def test_parse_date_handles_common_formats(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["31/02/1996", "not a date", "14/03/2099", "01/01/1800"])
def test_parse_date_rejects_impossible_dates(raw):
    assert parse_date(raw) is None


# --- Aadhaar extraction ----------------------------------------------------


def test_aadhaar_extraction_finds_expected_fields():
    fields = {f.field_name: f for f in extract_aadhaar_fields(result_from(AADHAAR_TEXT))}

    assert fields["aadhaar_number"].value == VALID_AADHAAR
    assert fields["date_of_birth"].value == "1996-03-14"
    assert fields["full_name"].value == "Ananya Sharma"
    assert fields["gender"].value == "Female"
    assert fields["postal_code"].value == "560001"


def test_valid_aadhaar_scores_higher_than_an_invalid_one():
    good = extract_aadhaar_fields(result_from(f"Aadhaar {VALID_AADHAAR}"))
    bad = extract_aadhaar_fields(result_from("Aadhaar 234123412345"))

    good_conf = next(f.confidence for f in good if f.field_name == "aadhaar_number")
    bad_conf = next(f.confidence for f in bad if f.field_name == "aadhaar_number")

    assert good_conf > bad_conf
    assert bad_conf < 0.7  # a failing checksum must land below the review threshold


def test_low_ocr_confidence_propagates_to_the_field():
    high = extract_aadhaar_fields(result_from(AADHAAR_TEXT, confidence=0.95))
    low = extract_aadhaar_fields(result_from(AADHAAR_TEXT, confidence=0.30))

    high_conf = next(f.confidence for f in high if f.field_name == "aadhaar_number")
    low_conf = next(f.confidence for f in low if f.field_name == "aadhaar_number")
    assert high_conf > low_conf


def test_document_furniture_is_not_mistaken_for_a_name():
    fields = {f.field_name: f.value for f in extract_aadhaar_fields(result_from(AADHAAR_TEXT))}
    assert fields.get("full_name") not in ("Government Of India", "Unique Identification")


# --- PAN extraction --------------------------------------------------------


def test_pan_extraction_finds_expected_fields():
    fields = {f.field_name: f for f in extract_pan_fields(result_from(PAN_TEXT))}

    assert fields["pan_number"].value == VALID_PAN
    assert fields["date_of_birth"].value == "1993-11-02"
    assert fields["full_name"].value == "Rohit Verma"
    assert fields["father_name"].value == "Suresh Verma"


def test_extract_fields_dispatches_on_document_type():
    aadhaar = {f.field_name for f in extract_fields("aadhaar", result_from(AADHAAR_TEXT))}
    pan = {f.field_name for f in extract_fields("pan", result_from(PAN_TEXT))}

    assert "aadhaar_number" in aadhaar
    assert "pan_number" in pan
    assert extract_fields("photo", result_from(AADHAAR_TEXT)) == []


def test_empty_text_yields_no_fields():
    assert extract_fields("aadhaar", OcrResult(text="", words=[])) == []


# --- Resume parsing --------------------------------------------------------


def test_sections_are_split_by_heading():
    sections = split_sections(RESUME_TEXT)
    assert "education" in sections
    assert "experience" in sections
    assert "skills" in sections
    assert any("IIT Madras" in line for line in sections["education"])


def test_resume_parser_extracts_contact_details():
    parsed = RuleBasedResumeParser().parse(result_from(RESUME_TEXT))

    assert parsed.candidate_name == "Meera Iyer"
    assert parsed.email == "meera.iyer@example.com"
    assert parsed.phone == "9876543210"


def test_resume_parser_extracts_education():
    parsed = RuleBasedResumeParser().parse(result_from(RESUME_TEXT))

    degrees = {entry["degree"] for entry in parsed.education}
    assert "BTECH" in degrees

    btech = next(e for e in parsed.education if e["degree"] == "BTECH")
    assert btech["year"] == 2018
    assert btech["cgpa"] == 8.7


def test_resume_parser_extracts_experience_and_totals_years():
    parsed = RuleBasedResumeParser().parse(result_from(RESUME_TEXT))

    assert len(parsed.experience) == 2
    current = [e for e in parsed.experience if e["is_current"]]
    assert len(current) == 1
    assert current[0]["end_year"] is None
    assert parsed.total_experience_years > 0


def test_resume_parser_extracts_skills():
    parsed = RuleBasedResumeParser().parse(result_from(RESUME_TEXT))

    assert "python" in parsed.skills
    assert "postgresql" in parsed.skills
    assert "docker" in parsed.skills


def test_resume_confidence_reflects_completeness():
    full = RuleBasedResumeParser().parse(result_from(RESUME_TEXT))
    sparse = RuleBasedResumeParser().parse(result_from("Just some words here"))

    assert full.confidence > sparse.confidence


def test_empty_resume_parses_without_error():
    parsed = RuleBasedResumeParser().parse(OcrResult(text="", words=[]))
    assert parsed.confidence == 0.0
    assert parsed.skills == []


# --- OcrResult confidence helpers -----------------------------------------


def test_mean_confidence_ignores_blank_words():
    result = OcrResult(
        text="a b",
        words=[OcrWord("a", 0.8), OcrWord("   ", 0.1), OcrWord("b", 0.6)],
    )
    assert result.mean_confidence == pytest.approx(0.7)


def test_confidence_for_unmatched_snippet_falls_back_to_mean():
    result = OcrResult(text="hello", words=[OcrWord("hello", 0.5)])
    assert result.confidence_for("nothing-like-this") == result.mean_confidence
