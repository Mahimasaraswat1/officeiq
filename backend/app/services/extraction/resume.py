"""Resume parsing into structured education / experience / skills (PRD A.7.3).

Section-and-pattern based rather than model-based: it is deterministic, needs no
API key, and is transparent when it gets something wrong. The `ResumeParser`
interface leaves room to swap in an LLM-backed parser in a later phase without
disturbing callers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.services.extraction.fields import EMAIL_RE, PHONE_RE
from app.services.ocr.base import OcrResult
from app.core.security import today_utc

# --- Section detection -----------------------------------------------------

SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "education": ("education", "academic", "qualification", "academics"),
    "experience": (
        "experience",
        "employment",
        "work history",
        "professional experience",
        "career",
    ),
    "skills": ("skills", "technical skills", "core competencies", "technologies"),
    "projects": ("projects", "personal projects"),
    "summary": ("summary", "objective", "profile", "about"),
    "certifications": ("certifications", "certificates", "courses"),
}

# A heading is a short line that is mostly a known section name.
HEADING_MAX_WORDS = 5

DEGREE_RE = re.compile(
    r"\b(ph\.?d|doctorate|m\.?tech|b\.?tech|m\.?e\b|b\.?e\b|m\.?sc|b\.?sc|m\.?c\.?a|"
    r"b\.?c\.?a|m\.?b\.?a|b\.?b\.?a|m\.?com|b\.?com|m\.?a\b|b\.?a\b|diploma|"
    r"bachelor[s']*|master[s']*|12th|10th|intermediate|high school)\b",
    re.IGNORECASE,
)

YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
YEAR_RANGE_RE = re.compile(
    r"\b(19[5-9]\d|20[0-4]\d)\s*(?:-|–|—|to)\s*(19[5-9]\d|20[0-4]\d|present|current|now)\b",
    re.IGNORECASE,
)
CGPA_RE = re.compile(r"\b(?:cgpa|gpa)\s*[:\-]?\s*(\d(?:\.\d{1,2})?)\s*(?:/\s*10)?\b", re.I)
PERCENT_RE = re.compile(r"\b(\d{2}(?:\.\d{1,2})?)\s*%")

# Common separators inside a skills block.
SKILL_SPLIT_RE = re.compile(r"[,;|•·•]|\s{3,}")

# A curated list keeps precision high; unknown comma-separated entries in a
# skills section are still captured, so coverage does not depend on this list.
KNOWN_SKILLS = {
    "python", "java", "javascript", "typescript", "c", "c++", "c#", "go", "rust",
    "ruby", "php", "swift", "kotlin", "scala", "r", "matlab", "sql", "html", "css",
    "react", "angular", "vue", "next.js", "node.js", "express", "django", "flask",
    "fastapi", "spring", "spring boot", "laravel", ".net", "rails",
    "postgresql", "mysql", "mongodb", "redis", "sqlite", "oracle", "cassandra",
    "elasticsearch", "dynamodb",
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform", "jenkins", "ansible",
    "git", "github", "gitlab", "ci/cd", "linux",
    "machine learning", "deep learning", "nlp", "computer vision", "tensorflow",
    "pytorch", "scikit-learn", "pandas", "numpy", "opencv", "keras",
    "excel", "power bi", "tableau", "jira", "figma", "agile", "scrum", "rest api",
    "graphql", "microservices", "kafka", "rabbitmq", "spark", "hadoop", "airflow",
}


@dataclass
class ParsedResume:
    candidate_name: str | None = None
    email: str | None = None
    phone: str | None = None
    total_experience_years: float | None = None
    education: list[dict] = field(default_factory=list)
    experience: list[dict] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def as_dict(self) -> dict:
        return {
            "candidate_name": self.candidate_name,
            "email": self.email,
            "phone": self.phone,
            "total_experience_years": self.total_experience_years,
            "education": self.education,
            "experience": self.experience,
            "skills": self.skills,
            "confidence": self.confidence,
        }


def _normalise_heading(line: str) -> str | None:
    """Return the canonical section name when `line` looks like its heading."""
    cleaned = re.sub(r"[^a-z\s]", " ", line.lower()).strip()
    if not cleaned or len(cleaned.split()) > HEADING_MAX_WORDS:
        return None
    for section, aliases in SECTION_ALIASES.items():
        for alias in aliases:
            if cleaned == alias or cleaned.startswith(alias):
                return section
    return None


def split_sections(text: str) -> dict[str, list[str]]:
    """Group non-empty lines under the most recent recognised heading."""
    sections: dict[str, list[str]] = {"_header": []}
    current = "_header"

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if heading := _normalise_heading(line):
            current = heading
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    return sections


def _guess_name(header_lines: list[str], text: str) -> str | None:
    """The candidate's name is nearly always the first substantive header line."""
    for line in header_lines[:5]:
        if EMAIL_RE.search(line) or PHONE_RE.search(line):
            continue
        if any(ch.isdigit() for ch in line):
            continue
        words = line.split()
        if not 1 < len(words) <= 4:
            continue
        if not all(w[0].isupper() for w in words if w and w[0].isalpha()):
            continue
        if _normalise_heading(line):
            continue
        return " ".join(w.title() for w in words)
    return None


def _parse_education(lines: list[str]) -> list[dict]:
    entries: list[dict] = []
    for line in lines:
        degree_match = DEGREE_RE.search(line)
        if not degree_match:
            continue

        years = YEAR_RE.findall(line)
        entry: dict = {
            "degree": degree_match.group(0).strip().upper().replace(".", ""),
            "detail": line[:300],
            "year": int(years[-1]) if years else None,
        }
        if cgpa := CGPA_RE.search(line):
            entry["cgpa"] = float(cgpa.group(1))
        if percent := PERCENT_RE.search(line):
            entry["percentage"] = float(percent.group(1))

        # Text before the degree keyword is usually the institution.
        prefix = line[: degree_match.start()].strip(" ,-–|")
        suffix = line[degree_match.end() :].strip(" ,-–|")
        institution = suffix if len(suffix) > len(prefix) else prefix
        institution = YEAR_RE.sub("", institution).strip(" ,-–|")
        if 2 < len(institution) < 120:
            entry["institution"] = institution

        entries.append(entry)
    return entries


def _parse_experience(lines: list[str]) -> tuple[list[dict], float | None]:
    entries: list[dict] = []
    total_years = 0.0
    current_year = today_utc().year

    for line in lines:
        range_match = YEAR_RANGE_RE.search(line)
        if not range_match:
            continue

        start = int(range_match.group(1))
        end_raw = range_match.group(2).lower()
        end = current_year if end_raw in ("present", "current", "now") else int(end_raw)
        if end < start:
            continue

        duration = round(end - start, 1)
        total_years += duration

        title = line[: range_match.start()].strip(" ,-–|")
        entries.append(
            {
                "title": title[:200] or None,
                "start_year": start,
                "end_year": None if end_raw in ("present", "current", "now") else end,
                "is_current": end_raw in ("present", "current", "now"),
                "duration_years": duration,
                "detail": line[:300],
            }
        )

    return entries, (round(total_years, 1) if entries else None)


def _parse_skills(lines: list[str], full_text: str) -> list[str]:
    found: set[str] = set()

    # 1. Everything listed inside an explicit skills section.
    for line in lines:
        for token in SKILL_SPLIT_RE.split(line):
            token = token.strip(" .:-\t")
            if 1 < len(token) <= 40 and not token.isdigit():
                found.add(token.lower())

    # 2. Known skills mentioned anywhere, which catches inline mentions.
    lowered = full_text.lower()
    for skill in KNOWN_SKILLS:
        pattern = rf"(?<![\w.+#]){re.escape(skill)}(?![\w.+#])"
        if re.search(pattern, lowered):
            found.add(skill)

    # Prefer the canonical spelling for anything we recognise.
    normalised = {s for s in found if s in KNOWN_SKILLS} | {
        s for s in found if s not in KNOWN_SKILLS and len(s.split()) <= 4
    }
    return sorted(normalised)[:60]


class ResumeParser:
    """Interface seam — a future LLM-backed parser implements `parse`."""

    name = "rule_based"

    def parse(self, result: OcrResult) -> ParsedResume:  # pragma: no cover - interface
        raise NotImplementedError


class RuleBasedResumeParser(ResumeParser):
    def parse(self, result: OcrResult) -> ParsedResume:
        text = result.text
        if not text.strip():
            return ParsedResume(confidence=0.0)

        sections = split_sections(text)
        parsed = ParsedResume()

        if email := EMAIL_RE.search(text):
            parsed.email = email.group(0).lower()
        if phone := PHONE_RE.search(text):
            parsed.phone = phone.group(1)

        parsed.candidate_name = _guess_name(sections.get("_header", []), text)
        parsed.education = _parse_education(
            sections.get("education", []) or text.splitlines()
        )
        parsed.experience, parsed.total_experience_years = _parse_experience(
            sections.get("experience", []) or text.splitlines()
        )
        parsed.skills = _parse_skills(sections.get("skills", []), text)

        # Confidence blends OCR quality with how much structure we recovered.
        signals = [
            bool(parsed.candidate_name),
            bool(parsed.email),
            bool(parsed.education),
            bool(parsed.experience),
            bool(parsed.skills),
        ]
        completeness = sum(signals) / len(signals)
        ocr_quality = result.mean_confidence or 0.5
        parsed.confidence = round(completeness * 0.6 + ocr_quality * 0.4, 4)

        return parsed


def get_resume_parser() -> ResumeParser:
    return RuleBasedResumeParser()


def parse_resume(result: OcrResult) -> ParsedResume:
    return get_resume_parser().parse(result)
