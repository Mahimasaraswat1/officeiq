"""Render a Dataset as a landscape A4 PDF (reportlab).

The PDF is the *presentation* format — something to attach to an email or file
with a compliance pack — so it carries a title block, repeating headers, zebra
striping and a page footer. Wide reports get proportional column widths rather
than being clipped.
"""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.reports.datasets import NUMERIC, Dataset

SLATE_900 = colors.HexColor("#0f172a")
SLATE_500 = colors.HexColor("#64748b")
SLATE_200 = colors.HexColor("#e2e8f0")
SLATE_50 = colors.HexColor("#f8fafc")

# Past this many rows a cell-by-cell PDF stops being a sensible artefact — the
# reader wants the spreadsheet. Truncation is stated on the page, never silent.
MAX_PDF_ROWS = 1200

_styles = getSampleStyleSheet()
TITLE = ParagraphStyle(
    "ReportTitle", parent=_styles["Title"], fontSize=16, alignment=TA_LEFT,
    textColor=SLATE_900, spaceAfter=2,
)
CONTEXT = ParagraphStyle(
    "ReportContext", parent=_styles["Normal"], fontSize=8.5, textColor=SLATE_500,
    spaceAfter=1,
)
CELL = ParagraphStyle(
    "ReportCell", parent=_styles["Normal"], fontSize=7.5, leading=9.5,
)
CELL_HEADER = ParagraphStyle(
    "ReportCellHeader", parent=CELL, fontSize=7.5, textColor=colors.white,
    fontName="Helvetica-Bold",
)


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(SLATE_500)
    canvas.drawString(15 * mm, 10 * mm, "OfficeIQ")
    canvas.drawRightString(
        document.pagesize[0] - 15 * mm, 10 * mm, f"Page {canvas.getPageNumber()}"
    )
    canvas.restoreState()


def render(dataset: Dataset) -> bytes:
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=dataset.title,
        author="OfficeIQ",
    )

    story: list = [Paragraph(dataset.title, TITLE)]
    for line in dataset.context:
        story.append(Paragraph(line, CONTEXT))
    story.append(
        Paragraph(f"Generated {dataset.generated_at:%Y-%m-%d %H:%M UTC}", CONTEXT)
    )
    story.append(Spacer(1, 6 * mm))

    rows = dataset.rows[:MAX_PDF_ROWS]
    truncated = len(dataset.rows) - len(rows)

    if not rows:
        story.append(Paragraph("No rows matched this report's filters.", CELL))
    else:
        # Paragraphs rather than raw strings so long values wrap instead of
        # overflowing the column and colliding with the next one.
        data = [[Paragraph(column.header, CELL_HEADER) for column in dataset.columns]]
        data += [[Paragraph(str(value), CELL) for value in row] for row in rows]

        available = document.width
        weights = [column.width for column in dataset.columns]
        total = sum(weights) or len(weights)
        widths = [available * (weight / total) for weight in weights]

        table = Table(data, colWidths=widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), SLATE_900),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.25, SLATE_200),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SLATE_50]),
        ]
        for index, column in enumerate(dataset.columns):
            if column.align == NUMERIC:
                style.append(("ALIGN", (index, 1), (index, -1), "RIGHT"))
        table.setStyle(TableStyle(style))
        story.append(table)

    if truncated > 0:
        story.append(Spacer(1, 4 * mm))
        story.append(
            Paragraph(
                f"{truncated:,} further row(s) are not shown — this PDF is capped at "
                f"{MAX_PDF_ROWS:,} rows. Export the same report as Excel for the "
                "complete set.",
                CONTEXT,
            )
        )

    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
