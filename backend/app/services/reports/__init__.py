"""Report generation (PRD A.7.8 / B.4.7).

One dataset, two renderers. `datasets.py` decides *what* a report contains;
`excel.py` and `pdf.py` decide only how it looks, so the two formats of a
report cannot drift apart.

Adding a format means adding a renderer and one entry in `FORMATS` — nothing
about the reports themselves changes.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.services.reports import excel, pdf
from app.services.reports.datasets import (
    REPORTS,
    Dataset,
    ReportSpec,
    build,
    visible_reports,
)


def _render_csv(dataset: Dataset) -> bytes:
    """CSV carries the table only — no title block, so it parses cleanly."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(dataset.headers)
    writer.writerows(dataset.rows)
    # BOM so Excel opens UTF-8 CSV without mangling accented names.
    return buffer.getvalue().encode("utf-8-sig")


@dataclass(frozen=True)
class ReportFormat:
    key: str
    extension: str
    media_type: str
    render: Callable[[Dataset], bytes]


FORMATS: dict[str, ReportFormat] = {
    "xlsx": ReportFormat(
        "xlsx",
        "xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        excel.render,
    ),
    "pdf": ReportFormat("pdf", "pdf", "application/pdf", pdf.render),
    "csv": ReportFormat("csv", "csv", "text/csv", _render_csv),
}


def render(dataset: Dataset, format_key: str) -> tuple[bytes, str, str]:
    """Return (content, media_type, filename) for a built dataset."""
    fmt = FORMATS[format_key]
    filename = (
        f"officeiq-{dataset.key.replace('_', '-')}-"
        f"{dataset.generated_at:%Y%m%d-%H%M}.{fmt.extension}"
    )
    return fmt.render(dataset), fmt.media_type, filename


def generate(
    db: Session, *, key: str, format_key: str, **filters: object
) -> tuple[bytes, str, str]:
    return render(build(db, key, **filters), format_key)


__all__ = [
    "FORMATS",
    "REPORTS",
    "Dataset",
    "ReportFormat",
    "ReportSpec",
    "build",
    "generate",
    "render",
    "visible_reports",
]
