"""Rule-based field extraction from OCR text (PRD A.7.3).

Each extractor returns candidate fields with a confidence in 0.0-1.0 that
combines two signals:

  * how confident OCR was about the characters involved, and
  * how strongly the value matches its expected format (Verhoeff checksum for
    Aadhaar, the PAN character grammar, a parseable date, and so on).

The result is a score HR can triage on rather than a raw OCR number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.services.ocr.base import OcrResult
from app.core.security import today_utc

# --- Patterns --------------------------------------------------------------

# Aadhaar: 12 digits, conventionally spaced in groups of four. Never starts 0/1.
AADHAAR_RE = re.compile(r"\b([2-9]\d{3})\s?(\d{4})\s?(\d{4})\b")
# PAN: five letters, four digits, one letter.
PAN_RE = re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b")
DOB_RE = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b")
DOB_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
PINCODE_RE = re.compile(r"\b([1-9]\d{5})\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE_RE = re.compile(r"(?:\+91[\s-]?)?\b([6-9]\d{9})\b")

GENDER_RE = re.compile(r"\b(MALE|FEMALE|TRANSGENDER)\b", re.IGNORECASE)

# Labels that precede a name on Indian ID documents.
# `[^\S\r\n]` is horizontal whitespace only — a plain \s would let the match
# run past the end of the line and swallow the next label (e.g. "... DOB").
_H = r"[^\S\r\n]"
NAME_LABEL_RE = re.compile(
    rf"(?:name|नाम){_H}*[:\-]?{_H}*([A-Z][A-Za-z]+(?:{_H}+[A-Z][A-Za-z]+){{0,3}})",
    re.IGNORECASE,
)
FATHER_NAME_RE = re.compile(
    rf"(?:father's|father|s/o|d/o|w/o){_H}*(?:name)?{_H}*[:\-]?{_H}*"
    rf"([A-Z][A-Za-z]+(?:{_H}+[A-Z][A-Za-z]+){{0,3}})",
    re.IGNORECASE,
)

# Words that look like names but are document furniture.
NAME_STOPWORDS = {
    "government",
    "india",
    "unique",
    "identification",
    "authority",
    "income",
    "tax",
    "department",
    "permanent",
    "account",
    "number",
    "card",
    "aadhaar",
    "male",
    "female",
    "date",
    "birth",
    "signature",
    "father",
}


@dataclass
class FieldCandidate:
    """One extracted value, ready to be persisted as an ExtractedField."""

    field_name: str
    value: str
    confidence: float

    def clamped(self) -> "FieldCandidate":
        return FieldCandidate(
            field_name=self.field_name,
            value=self.value,
            confidence=round(max(0.0, min(1.0, self.confidence)), 4),
        )


# --- Validators ------------------------------------------------------------

# Verhoeff tables — the checksum UIDAI uses for Aadhaar numbers.
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def is_valid_aadhaar(number: str) -> bool:
    """Verhoeff checksum. Catches most OCR digit misreads."""
    digits = re.sub(r"\D", "", number)
    if len(digits) != 12 or digits[0] in "01":
        return False
    checksum = 0
    for index, digit in enumerate(reversed(digits)):
        checksum = _VERHOEFF_D[checksum][_VERHOEFF_P[index % 8][int(digit)]]
    return checksum == 0


def is_valid_pan(pan: str) -> bool:
    """PAN grammar check, including the 4th-character entity code."""
    pan = pan.strip().upper()
    if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan):
        return False
    # 4th character encodes holder type; 'P' is an individual.
    return pan[3] in "ABCFGHLJPTE"


def parse_date(raw: str) -> date | None:
    """Parse the date formats that appear on Indian ID documents."""
    for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(raw.strip(), pattern).date()
        except ValueError:
            continue
        # Reject implausible dates rather than storing OCR noise.
        if date(1900, 1, 1) <= parsed <= today_utc() + timedelta(days=1):
            return parsed
    return None


# --- Extractors ------------------------------------------------------------


def _clean_name(raw: str) -> str | None:
    parts = [p for p in raw.split() if p.lower() not in NAME_STOPWORDS]
    if not parts:
        return None
    name = " ".join(parts).title()
    return name if 2 <= len(name) <= 100 else None


def extract_aadhaar_fields(result: OcrResult) -> list[FieldCandidate]:
    text = result.text
    upper = text.upper()
    candidates: list[FieldCandidate] = []

    for match in AADHAAR_RE.finditer(text):
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        valid = is_valid_aadhaar(digits)
        ocr_conf = result.confidence_for(raw)
        # A passing checksum is strong evidence; a failing one is a red flag.
        confidence = ocr_conf * (1.0 if valid else 0.45)
        candidates.append(
            FieldCandidate("aadhaar_number", digits, confidence).clamped()
        )
        if valid:
            break  # first checksum-valid number wins

    for match in DOB_RE.finditer(text):
        parsed = parse_date(match.group(0))
        if parsed:
            candidates.append(
                FieldCandidate(
                    "date_of_birth",
                    parsed.isoformat(),
                    result.confidence_for(match.group(0)),
                ).clamped()
            )
            break

    if name_match := NAME_LABEL_RE.search(text):
        if name := _clean_name(name_match.group(1)):
            candidates.append(
                FieldCandidate("full_name", name, result.confidence_for(name)).clamped()
            )

    if father_match := FATHER_NAME_RE.search(text):
        if father := _clean_name(father_match.group(1)):
            candidates.append(
                FieldCandidate(
                    "father_name", father, result.confidence_for(father)
                ).clamped()
            )

    if gender_match := GENDER_RE.search(upper):
        gender = gender_match.group(1).title()
        candidates.append(
            FieldCandidate("gender", gender, result.confidence_for(gender)).clamped()
        )

    if pin_match := PINCODE_RE.search(text):
        pincode = pin_match.group(1)
        candidates.append(
            FieldCandidate("postal_code", pincode, result.confidence_for(pincode)).clamped()
        )

    return _dedupe(candidates)


def extract_pan_fields(result: OcrResult) -> list[FieldCandidate]:
    text = result.text
    candidates: list[FieldCandidate] = []

    for match in PAN_RE.finditer(text.upper()):
        pan = match.group(1)
        valid = is_valid_pan(pan)
        confidence = result.confidence_for(pan) * (1.0 if valid else 0.5)
        candidates.append(FieldCandidate("pan_number", pan, confidence).clamped())
        if valid:
            break

    for match in DOB_RE.finditer(text):
        parsed = parse_date(match.group(0))
        if parsed:
            candidates.append(
                FieldCandidate(
                    "date_of_birth",
                    parsed.isoformat(),
                    result.confidence_for(match.group(0)),
                ).clamped()
            )
            break

    if name_match := NAME_LABEL_RE.search(text):
        if name := _clean_name(name_match.group(1)):
            candidates.append(
                FieldCandidate("full_name", name, result.confidence_for(name)).clamped()
            )

    if father_match := FATHER_NAME_RE.search(text):
        if father := _clean_name(father_match.group(1)):
            candidates.append(
                FieldCandidate(
                    "father_name", father, result.confidence_for(father)
                ).clamped()
            )

    return _dedupe(candidates)


def extract_generic_fields(result: OcrResult) -> list[FieldCandidate]:
    """Best-effort contact details for certificates and unclassified files."""
    text = result.text
    candidates: list[FieldCandidate] = []

    if email_match := EMAIL_RE.search(text):
        email = email_match.group(0).lower()
        candidates.append(
            FieldCandidate("email", email, result.confidence_for(email)).clamped()
        )

    if phone_match := PHONE_RE.search(text):
        phone = phone_match.group(1)
        candidates.append(
            FieldCandidate("phone", phone, result.confidence_for(phone)).clamped()
        )

    if pin_match := PINCODE_RE.search(text):
        pincode = pin_match.group(1)
        candidates.append(
            FieldCandidate("postal_code", pincode, result.confidence_for(pincode)).clamped()
        )

    return _dedupe(candidates)


def _dedupe(candidates: list[FieldCandidate]) -> list[FieldCandidate]:
    """Keep the highest-confidence candidate per field name."""
    best: dict[str, FieldCandidate] = {}
    for candidate in candidates:
        if not candidate.value:
            continue
        current = best.get(candidate.field_name)
        if current is None or candidate.confidence > current.confidence:
            best[candidate.field_name] = candidate
    return list(best.values())


# Maps a document type to its extractor. Adding a new document type is a
# one-line change here plus the extractor function itself.
EXTRACTORS = {
    "aadhaar": extract_aadhaar_fields,
    "pan": extract_pan_fields,
    "certificate": extract_generic_fields,
    "photo": lambda _result: [],
    "other": extract_generic_fields,
}


def extract_fields(document_type: str, result: OcrResult) -> list[FieldCandidate]:
    extractor = EXTRACTORS.get(document_type, extract_generic_fields)
    return extractor(result)
