"""Downloadable reports in Excel, PDF and CSV (PRD A.7.8 / B.4.7).

Every export is written to the audit log, including its filters and row count:
a report is a copy of company data leaving the system, so who took what, and
when, is exactly the kind of thing the audit trail exists for.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.deps import CurrentUser, DbSession, HrUser
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.core.ratelimit import report_rate_limit
from app.models.enums import AuditAction, OnboardingStatus, UserRole
from app.services.audit import record_audit
from app.services.reports import FORMATS, REPORTS, build, render, visible_reports

router = APIRouter(prefix="/reports", tags=["Reports"])


class ReportFormatInfo(BaseModel):
    key: str
    extension: str
    media_type: str


class ReportInfo(BaseModel):
    key: str
    label: str
    description: str
    admin_only: bool
    supports_employee_filters: bool
    supports_audit_filters: bool
    formats: list[str]


class ReportCatalogue(BaseModel):
    reports: list[ReportInfo]
    formats: list[ReportFormatInfo]


@router.get(
    "", response_model=ReportCatalogue, summary="Reports available to me (HR/Admin)"
)
def catalogue(_: HrUser, user: CurrentUser) -> ReportCatalogue:
    """The list is role-filtered, so HR is never offered an export they cannot run."""
    return ReportCatalogue(
        reports=[
            ReportInfo(
                key=spec.key,
                label=spec.label,
                description=spec.description,
                admin_only=spec.admin_only,
                supports_employee_filters=spec.supports_employee_filters,
                supports_audit_filters=spec.supports_audit_filters,
                formats=list(FORMATS),
            )
            for spec in visible_reports(user.role)
        ],
        formats=[
            ReportFormatInfo(key=f.key, extension=f.extension, media_type=f.media_type)
            for f in FORMATS.values()
        ],
    )


@router.get(
    "/{report_key}",
    summary="Download a report (HR/Admin; some are Admin-only)",
    response_class=Response,
    # Per-user: each export scans and renders the whole table.
    dependencies=[Depends(report_rate_limit)],
    responses={
        200: {
            "content": {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
                "application/pdf": {},
                "text/csv": {},
            },
            "description": "The rendered report as a file attachment.",
        }
    },
)
def download_report(
    report_key: str,
    request: Request,
    db: DbSession,
    _: HrUser,
    user: CurrentUser,
    format: Annotated[str, Query(description="xlsx, pdf or csv")] = "xlsx",
    department: str | None = None,
    status: OnboardingStatus | None = None,
    action: Annotated[str | None, Query(description="Audit trail only")] = None,
    actor: Annotated[str | None, Query(description="Audit trail only")] = None,
    entity_type: Annotated[str | None, Query(description="Audit trail only")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Response:
    spec = REPORTS.get(report_key)
    if spec is None:
        raise NotFoundError(f"No such report: {report_key!r}.")
    if spec.admin_only and user.role is not UserRole.ADMIN:
        raise PermissionDeniedError("This report is available to Admins only.")

    format_key = format.lower()
    if format_key not in FORMATS:
        raise ValidationError(
            f"Unsupported format {format!r}. Choose one of: {', '.join(FORMATS)}."
        )
    if date_from and date_to and date_from > date_to:
        raise ValidationError("date_from must not be later than date_to.")

    filters = {
        "department": department,
        "status": status,
        "action": action,
        "actor": actor,
        "entity_type": entity_type,
        "date_from": date_from,
        "date_to": date_to,
    }
    dataset = build(db, report_key, **filters)
    content, media_type, filename = render(dataset, format_key)

    record_audit(
        db,
        action=AuditAction.REPORT_EXPORTED,
        actor=user,
        entity_type="report",
        entity_id=report_key,
        detail={
            "format": format_key,
            "rows": len(dataset.rows),
            # Only the filters that were actually applied, so the entry reads
            # as what was asked for rather than a wall of nulls.
            "filters": {
                key: (value.value if hasattr(value, "value") else str(value))
                for key, value in filters.items()
                if value is not None
            },
        },
        request=request,
    )
    db.commit()

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            # The browser needs this exposed to read the filename via fetch.
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )
