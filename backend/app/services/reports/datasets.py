"""What each report contains — the queries, independent of output format.

A dataset is a plain table: a title, some context lines, column headers and
rows. Both the Excel and the PDF renderer consume the *same* Dataset, so the
two formats of one report can never disagree about a number — a bug fixed here
is fixed in both.

Values are rendered to strings/numbers at this layer rather than in the
renderers, so date formatting and "—" for empty are also decided once.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import utcnow, today_utc
from app.models.audit import AuditLog
from app.models.document import Document
from app.models.employee import Employee
from app.models.enums import (
    DocumentStatus,
    DocumentType,
    OnboardingStatus,
    TaskStatus,
    UserRole,
)
from app.models.task import EmployeeTask
from app.models.user import User
from app.models.verification import VerificationCheck
from app.services.review import REQUIRED_DOCUMENT_TYPES

# Column alignment hints the renderers honour. Numbers right, everything left.
NUMERIC = "numeric"


@dataclass
class Column:
    header: str
    width: int = 18
    align: str = "left"


@dataclass
class Dataset:
    key: str
    title: str
    columns: list[Column]
    rows: list[list[object]]
    # Short "Department: Engineering · 14 rows" lines printed under the title.
    context: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=utcnow)

    @property
    def headers(self) -> list[str]:
        return [column.header for column in self.columns]


def _fmt_date(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return value.strftime("%Y-%m-%d")


def _or_dash(value: object) -> object:
    return "—" if value in (None, "") else value


def _employee_filters(department: str | None, status: OnboardingStatus | None) -> list:
    filters = []
    if department:
        filters.append(func.lower(Employee.department) == department.strip().lower())
    if status:
        filters.append(Employee.onboarding_status == status)
    return filters


def _context(department: str | None, status: OnboardingStatus | None, count: int) -> list[str]:
    parts = [f"Department: {department}" if department else "All departments"]
    parts.append(f"Status: {status.value}" if status else "All statuses")
    parts.append(f"{count} row{'' if count == 1 else 's'}")
    return [" · ".join(parts)]


# --- Reports ---------------------------------------------------------------


def employee_roster(
    db: Session,
    *,
    department: str | None = None,
    status: OnboardingStatus | None = None,
    **_: object,
) -> Dataset:
    """Every employee profile with its employment and onboarding facts."""
    employees = db.scalars(
        select(Employee)
        .where(*_employee_filters(department, status))
        .order_by(Employee.first_name, Employee.last_name)
    ).all()

    rows = [
        [
            employee.employee_code,
            employee.full_name,
            employee.work_email,
            _or_dash(employee.department),
            _or_dash(employee.designation),
            _fmt_date(employee.date_of_joining),
            _or_dash(employee.reporting_manager),
            employee.onboarding_status.value,
            _fmt_date(employee.created_at),
        ]
        for employee in employees
    ]

    return Dataset(
        key="employee_roster",
        title="Employee roster",
        columns=[
            Column("Code", 12),
            Column("Name", 24),
            Column("Work email", 30),
            Column("Department", 18),
            Column("Designation", 22),
            Column("Joining date", 14),
            Column("Reporting manager", 22),
            Column("Onboarding status", 20),
            Column("Profile created", 18),
        ],
        rows=rows,
        context=_context(department, status, len(rows)),
    )


def onboarding_status(
    db: Session,
    *,
    department: str | None = None,
    status: OnboardingStatus | None = None,
    **_: object,
) -> Dataset:
    """Where each person is, how long they have been there, and what is blocking."""
    employees = db.scalars(
        select(Employee)
        .where(*_employee_filters(department, status))
        .order_by(Employee.onboarding_status, Employee.first_name)
    ).all()

    now = utcnow()
    rows = []
    for employee in employees:
        documents = db.scalars(
            select(Document).where(Document.employee_id == employee.id)
        ).all()
        approved_types = {
            d.document_type for d in documents if d.status is DocumentStatus.APPROVED
        }
        missing = sorted(t.value for t in REQUIRED_DOCUMENT_TYPES - approved_types)

        outstanding = db.scalar(
            select(func.count())
            .select_from(EmployeeTask)
            .where(
                EmployeeTask.employee_id == employee.id,
                EmployeeTask.is_mandatory.is_(True),
                EmployeeTask.status.notin_([TaskStatus.COMPLETED, TaskStatus.WAIVED]),
            )
        ) or 0

        # Days elapsed, and for finished onboardings how long it actually took.
        elapsed = (now - employee.created_at).days
        took = (
            (employee.onboarding_completed_at - employee.created_at).days
            if employee.onboarding_completed_at
            else None
        )

        rows.append([
            employee.employee_code,
            employee.full_name,
            _or_dash(employee.department),
            employee.onboarding_status.value,
            elapsed,
            took if took is not None else "—",
            len(documents),
            ", ".join(missing) if missing else "none",
            outstanding,
        ])

    return Dataset(
        key="onboarding_status",
        title="Onboarding status",
        columns=[
            Column("Code", 12),
            Column("Name", 24),
            Column("Department", 18),
            Column("Stage", 20),
            Column("Days since created", 18, NUMERIC),
            Column("Days to complete", 16, NUMERIC),
            Column("Documents", 11, NUMERIC),
            Column("Missing approvals", 28),
            Column("Mandatory tasks open", 18, NUMERIC),
        ],
        rows=rows,
        context=_context(department, status, len(rows)),
    )


def document_compliance(
    db: Session,
    *,
    department: str | None = None,
    status: OnboardingStatus | None = None,
    **_: object,
) -> Dataset:
    """One column per required document type, so gaps are visible at a glance."""
    employees = db.scalars(
        select(Employee)
        .where(*_employee_filters(department, status))
        .order_by(Employee.first_name)
    ).all()

    required = sorted(REQUIRED_DOCUMENT_TYPES, key=lambda t: t.value)
    rows = []
    for employee in employees:
        documents = db.scalars(
            select(Document).where(Document.employee_id == employee.id)
        ).all()
        by_type: dict[DocumentType, str] = {}
        for document in documents:
            # Approved beats anything else; otherwise show the latest state.
            if by_type.get(document.document_type) == "approved":
                continue
            by_type[document.document_type] = document.status.value

        verifications = db.scalars(
            select(VerificationCheck).where(VerificationCheck.employee_id == employee.id)
        ).all()
        failed = sorted(
            {v.check_type.value for v in verifications if v.status.value == "failed"}
        )

        rows.append(
            [employee.employee_code, employee.full_name, _or_dash(employee.department)]
            + [by_type.get(doc_type, "not uploaded") for doc_type in required]
            + [", ".join(failed) if failed else "none"]
        )

    return Dataset(
        key="document_compliance",
        title="Document compliance",
        columns=(
            [Column("Code", 12), Column("Name", 24), Column("Department", 18)]
            + [Column(doc_type.value.title(), 16) for doc_type in required]
            + [Column("Failed ID checks", 18)]
        ),
        rows=rows,
        context=_context(department, status, len(rows))
        + ["Required for completion: " + ", ".join(t.value for t in required)],
    )


def task_completion(
    db: Session,
    *,
    department: str | None = None,
    status: OnboardingStatus | None = None,
    **_: object,
) -> Dataset:
    """Per-employee task progress, worst compliance first."""
    employees = db.scalars(
        select(Employee)
        .where(*_employee_filters(department, status))
        .order_by(Employee.first_name)
    ).all()

    today = today_utc()
    rows = []
    for employee in employees:
        tasks = db.scalars(
            select(EmployeeTask).where(EmployeeTask.employee_id == employee.id)
        ).all()
        if not tasks:
            continue

        completed = sum(1 for t in tasks if t.status is TaskStatus.COMPLETED)
        waived = sum(1 for t in tasks if t.status is TaskStatus.WAIVED)
        overdue = sum(1 for t in tasks if t.is_overdue(today))
        mandatory_open = sum(
            1 for t in tasks if t.is_mandatory and not t.is_closed
        )
        closed = completed + waived

        rows.append([
            employee.employee_code,
            employee.full_name,
            _or_dash(employee.department),
            len(tasks),
            completed,
            waived,
            len(tasks) - closed,
            overdue,
            mandatory_open,
            round(closed / len(tasks) * 100),
        ])

    # Least-complete first: this report exists to find who needs chasing.
    rows.sort(key=lambda row: (row[-1], -row[7]))

    return Dataset(
        key="task_completion",
        title="Task & training completion",
        columns=[
            Column("Code", 12),
            Column("Name", 24),
            Column("Department", 18),
            Column("Assigned", 10, NUMERIC),
            Column("Completed", 11, NUMERIC),
            Column("Waived", 9, NUMERIC),
            Column("Open", 8, NUMERIC),
            Column("Overdue", 10, NUMERIC),
            Column("Mandatory open", 15, NUMERIC),
            Column("Complete %", 12, NUMERIC),
        ],
        rows=rows,
        context=_context(department, status, len(rows))
        + ["Employees with no assigned tasks are omitted."],
    )


# Exports of the audit trail are capped: it is an append-only table that grows
# without bound, and a request for "everything" would otherwise try to
# materialise the whole history in memory.
AUDIT_EXPORT_LIMIT = 5000


def audit_trail(
    db: Session,
    *,
    action: str | None = None,
    actor: str | None = None,
    entity_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    **_: object,
) -> Dataset:
    """The audit log, filtered the same way the API filters it (Admin only)."""
    from app.api.v1.audit import build_audit_filters

    filters = build_audit_filters(
        action=action,
        actor=actor,
        entity_type=entity_type,
        entity_id=None,
        date_from=date_from,
        date_to=date_to,
    )
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0
    entries = db.scalars(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc())
        .limit(AUDIT_EXPORT_LIMIT)
    ).all()

    rows = [
        [
            _fmt_date(entry.created_at),
            _or_dash(entry.actor_email),
            _or_dash(entry.actor_role),
            entry.action,
            _or_dash(entry.entity_type),
            _or_dash(entry.entity_id),
            _or_dash(entry.ip_address),
            str(entry.detail) if entry.detail else "—",
        ]
        for entry in entries
    ]

    context = [f"{len(rows)} of {total} matching entries"]
    if total > len(rows):
        # Never let a truncated export pass for a complete one.
        context.append(
            f"Truncated to the {AUDIT_EXPORT_LIMIT} most recent — narrow the "
            "date range to export the rest."
        )
    if date_from or date_to:
        context.append(f"Range: {date_from or 'start'} to {date_to or 'today'}")
    if action:
        context.append(f"Action: {action}")
    if actor:
        context.append(f"Actor matching: {actor}")

    return Dataset(
        key="audit_trail",
        title="Audit trail",
        columns=[
            Column("When", 18),
            Column("Actor", 28),
            Column("Role", 10),
            Column("Action", 26),
            Column("Entity", 16),
            Column("Entity id", 38),
            Column("IP", 16),
            Column("Detail", 60),
        ],
        rows=rows,
        context=context,
    )


def user_accounts(db: Session, **_: object) -> Dataset:
    """Staff accounts and their access — an access-review artefact (Admin only)."""
    users = db.scalars(select(User).order_by(User.role, User.full_name)).all()

    rows = [
        [
            user.full_name,
            user.email,
            user.role.value,
            "active" if user.is_active else "deactivated",
            _fmt_date(user.last_login_at),
            "yes" if user.locked_until else "no",
            _fmt_date(user.created_at),
        ]
        for user in users
    ]

    return Dataset(
        key="user_accounts",
        title="User accounts",
        columns=[
            Column("Name", 24),
            Column("Email", 30),
            Column("Role", 12),
            Column("State", 14),
            Column("Last sign-in", 18),
            Column("Locked", 9),
            Column("Created", 18),
        ],
        rows=rows,
        context=[f"{len(rows)} account{'' if len(rows) == 1 else 's'}"],
    )


@dataclass(frozen=True)
class ReportSpec:
    key: str
    label: str
    description: str
    builder: Callable[..., Dataset]
    # Admin-only reports carry account or audit data HR has no need to export.
    admin_only: bool = False
    supports_employee_filters: bool = True
    supports_audit_filters: bool = False


REPORTS: dict[str, ReportSpec] = {
    spec.key: spec
    for spec in [
        ReportSpec(
            "employee_roster",
            "Employee roster",
            "Every employee profile with employment details and onboarding stage.",
            employee_roster,
        ),
        ReportSpec(
            "onboarding_status",
            "Onboarding status",
            "Stage, elapsed time, missing document approvals and open mandatory tasks.",
            onboarding_status,
        ),
        ReportSpec(
            "document_compliance",
            "Document compliance",
            "One column per required document type, plus any failed ID checks.",
            document_compliance,
        ),
        ReportSpec(
            "task_completion",
            "Task & training completion",
            "Per-employee task progress, least complete first.",
            task_completion,
        ),
        ReportSpec(
            "audit_trail",
            "Audit trail",
            "Filtered export of the append-only audit log.",
            audit_trail,
            admin_only=True,
            supports_employee_filters=False,
            supports_audit_filters=True,
        ),
        ReportSpec(
            "user_accounts",
            "User accounts",
            "Staff accounts, roles and last sign-in — for periodic access review.",
            user_accounts,
            admin_only=True,
            supports_employee_filters=False,
        ),
    ]
}


def visible_reports(role: UserRole) -> list[ReportSpec]:
    return [
        spec for spec in REPORTS.values() if not spec.admin_only or role is UserRole.ADMIN
    ]


def build(db: Session, key: str, **filters: object) -> Dataset:
    return REPORTS[key].builder(db, **filters)
