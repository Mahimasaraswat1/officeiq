"""Builders for realistic test files (images and PDFs).

These produce genuine PNG/JPEG/PDF bytes rather than fixtures checked into the
repo, so the upload path, magic-byte sniffing, and OCR all see real files.
"""

from __future__ import annotations

import io

# A checksum-valid Aadhaar number (passes Verhoeff) used across the tests.
VALID_AADHAAR = "234123412346"
VALID_PAN = "ABCPD1234E"

AADHAAR_TEXT = f"""Government of India
Unique Identification Authority of India
Name: Ananya Sharma
DOB: 14/03/1996
Gender: Female
{VALID_AADHAAR[0:4]} {VALID_AADHAAR[4:8]} {VALID_AADHAAR[8:12]}
Address: 12 MG Road Bengaluru Karnataka 560001
"""

PAN_TEXT = f"""INCOME TAX DEPARTMENT
GOVT. OF INDIA
Permanent Account Number Card
{VALID_PAN}
Name: Rohit Verma
Father's Name: Suresh Verma
Date of Birth: 02/11/1993
"""

RESUME_TEXT = """Meera Iyer
meera.iyer@example.com
9876543210

Summary
Backend engineer focused on distributed systems.

Experience
Senior Software Engineer, Acme Corp 2021 - Present
Software Engineer, Globex 2018 - 2021

Education
B.Tech Computer Science, IIT Madras 2018 CGPA: 8.7
12th Standard, Kendriya Vidyalaya 2014 88%

Skills
Python, FastAPI, PostgreSQL, Docker, Kubernetes, AWS, React
"""


def make_png(width: int = 400, height: int = 200, colour: str = "white") -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def make_jpeg(width: int = 400, height: int = 200) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


def make_text_image(text: str, width: int = 1200, height: int = 700) -> bytes:
    """Render text onto a PNG at a size Tesseract can read reliably."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    font = None
    for path in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        try:
            font = ImageFont.truetype(path, 28)
            break
        except OSError:
            continue
    if font is None:  # pragma: no cover - falls back on unusual hosts
        font = ImageFont.load_default()

    y = 24
    for line in text.strip().splitlines():
        draw.text((28, y), line.strip(), fill="black", font=font)
        y += 40

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def make_text_pdf(text: str) -> bytes:
    """A PDF with a real embedded text layer (no OCR needed to read it)."""
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((60, 80), text.strip(), fontsize=11)
    data = document.tobytes()
    document.close()
    return data


def make_scanned_pdf(text: str) -> bytes:
    """A PDF whose only content is a rasterised image — forces the OCR path."""
    import fitz

    image_bytes = make_text_image(text)
    document = fitz.open()
    page = document.new_page(width=612, height=792)
    page.insert_image(fitz.Rect(20, 20, 592, 372), stream=image_bytes)
    data = document.tobytes()
    document.close()
    return data


def upload_file(client, headers, employee_id, *, data: bytes, filename: str,
                document_type: str, content_type: str = "image/png"):
    """POST a multipart document upload."""
    return client.post(
        f"/api/v1/employees/{employee_id}/documents",
        headers=headers,
        files={"file": (filename, data, content_type)},
        data={"document_type": document_type},
    )
