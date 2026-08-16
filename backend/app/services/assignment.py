"""Rule-driven task assignment (PRD A.7.5 / B.4.5).

Rules live in the database so HR can change onboarding policy without a deploy.
Evaluation is a **union**: every active rule whose conditions match contributes
its templates, and duplicates collapse to one task. Union rather than
first-match-wins means a department rule and a designation rule compose the way
HR expects, instead of one silently suppressing the other.

Assignment is idempotent — running it repeatedly never duplicates a task, so it
is safe to call on every review pass.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.security import utcnow
from app.models.document import Document
from app.models.employee import Employee
from app.models.enums import (
    AuditAction,
    DocumentStatus,
    TaskCategory,
    TaskStatus,
)
from app.models.task import AssignmentRule, AssignmentRuleItem, EmployeeTask, TaskTemplate
from app.models.user import User
from app.services.audit import record_audit
from app.services.notifications import notify_tasks_assigned

logger = logging.getLogger(__name__)


@dataclass
class ResolvedItem:
    """One template selected for an employee, with effective settings applied."""

    template: TaskTemplate
    rule: AssignmentRule | None
    due_days: int | None
    is_mandatory: bool


@dataclass
class AssignmentResult:
    assigned: list[EmployeeTask] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    matched_rules: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.assigned)


def _active_rules(db: Session) -> list[AssignmentRule]:
    return list(
        db.scalars(
            select(AssignmentRule)
            .where(AssignmentRule.is_active.is_(True))
            .options(
                selectinload(AssignmentRule.items).selectinload(
                    AssignmentRuleItem.template
                )
            )
            .order_by(AssignmentRule.priority, AssignmentRule.created_at)
        ).all()
    )


def resolve_templates(db: Session, employee: Employee) -> list[ResolvedItem]:
    """Return the templates that apply to this employee, de-duplicated.

    When two rules select the same template, the stricter setting wins: the
    earlier due date and mandatory over optional. Silently downgrading a
    mandatory item because a second rule happened to mark it optional would be
    the wrong default for a compliance checklist.
    """
    resolved: dict[str, ResolvedItem] = {}

    for rule in _active_rules(db):
        if not rule.matches(employee):
            continue

        for item in rule.items:
            template = item.template
            if template is None or not template.is_active:
                continue

            due_days = (
                item.due_days_override
                if item.due_days_override is not None
                else template.default_due_days
            )
            is_mandatory = (
                item.is_mandatory_override
                if item.is_mandatory_override is not None
                else template.is_mandatory
            )

            existing = resolved.get(template.code)
            if existing is None:
                resolved[template.code] = ResolvedItem(
                    template=template,
                    rule=rule,
                    due_days=due_days,
                    is_mandatory=is_mandatory,
                )
                continue

            # Keep the stricter of the two.
            if due_days is not None and (
                existing.due_days is None or due_days < existing.due_days
            ):
                existing.due_days = due_days
            existing.is_mandatory = existing.is_mandatory or is_mandatory

    return list(resolved.values())


def preview_assignment(
    db: Session, *, department: str | None, designation: str | None
) -> tuple[list[AssignmentRule], list[ResolvedItem]]:
    """What *would* be assigned for these attributes — used by the rule editor.

    Builds a detached stand-in employee so HR can try rule changes without
    touching a real record.
    """
    probe = Employee(
        first_name="Preview",
        last_name="Employee",
        work_email="preview@example.invalid",
        employee_code="PREVIEW",
        department=department,
        designation=designation,
    )
    matched = [rule for rule in _active_rules(db) if rule.matches(probe)]
    return matched, resolve_templates(db, probe)


def _due_date_for(employee: Employee, due_days: int | None) -> date | None:
    if due_days is None:
        return None
    # Relative to joining where known, otherwise to the assignment date.
    anchor = employee.date_of_joining or date.today()
    return anchor + timedelta(days=due_days)


def assign_tasks(
    db: Session, *, employee: Employee, actor: User | None = None
) -> AssignmentResult:
    """Assign every applicable template not already assigned to this employee."""
    result = AssignmentResult()

    existing_template_ids = set(
        db.scalars(
            select(EmployeeTask.template_id).where(
                EmployeeTask.employee_id == employee.id,
                EmployeeTask.template_id.is_not(None),
            )
        ).all()
    )

    for item in resolve_templates(db, employee):
        template = item.template
        if item.rule is not None and item.rule.name not in result.matched_rules:
            result.matched_rules.append(item.rule.name)

        if template.id in existing_template_ids:
            result.skipped_existing.append(template.code)
            continue

        task = EmployeeTask(
            employee_id=employee.id,
            template_id=template.id,
            rule_id=item.rule.id if item.rule else None,
            # Snapshot, so later template edits never rewrite assigned history.
            title=template.title,
            description=template.description,
            category=template.category,
            resource_url=template.resource_url,
            required_document_type=template.required_document_type,
            is_mandatory=item.is_mandatory,
            status=TaskStatus.PENDING,
            due_date=_due_date_for(employee, item.due_days),
            assigned_by_id=actor.id if actor else None,
        )
        db.add(task)
        result.assigned.append(task)

    if result.assigned:
        db.flush()
        record_audit(
            db,
            action=AuditAction.TASKS_ASSIGNED,
            actor=actor,
            actor_email=None if actor else "system",
            entity_type="employee",
            entity_id=employee.id,
            detail={
                "assigned": [t.title for t in result.assigned],
                "count": len(result.assigned),
                "rules": result.matched_rules,
            },
        )

        # A checklist item may already be satisfied by a document approved
        # before the task existed.
        sync_document_checklist(db, employee=employee, actor=None)

        notify_tasks_assigned(
            db, employee=employee, count=len(result.assigned), actor=actor
        )

    return result


# --- Document checklist ----------------------------------------------------


def sync_document_checklist(
    db: Session, *, employee: Employee, actor: User | None = None
) -> list[EmployeeTask]:
    """Close checklist items whose required document has been approved.

    Keeps the digital checklist honest without asking anyone to tick a box that
    the system can already answer for itself.
    """
    tasks = db.scalars(
        select(EmployeeTask).where(
            EmployeeTask.employee_id == employee.id,
            EmployeeTask.category == TaskCategory.DOCUMENT_CHECKLIST,
            EmployeeTask.required_document_type.is_not(None),
            EmployeeTask.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]),
        )
    ).all()
    if not tasks:
        return []

    approved_types = set(
        db.scalars(
            select(Document.document_type).where(
                Document.employee_id == employee.id,
                Document.status == DocumentStatus.APPROVED,
            )
        ).all()
    )

    closed: list[EmployeeTask] = []
    for task in tasks:
        if task.required_document_type in approved_types:
            task.status = TaskStatus.COMPLETED
            task.completed_at = utcnow()
            task.completed_by_id = actor.id if actor else None
            task.notes = (task.notes or "") + (
                "\nCompleted automatically: the required document was approved."
            ).strip()
            closed.append(task)

    if closed:
        db.flush()
        record_audit(
            db,
            action=AuditAction.TASK_COMPLETED,
            actor=actor,
            actor_email=None if actor else "system",
            entity_type="employee",
            entity_id=employee.id,
            detail={
                "auto_completed": [t.title for t in closed],
                "reason": "required document approved",
            },
        )
    return closed


# --- Progress --------------------------------------------------------------


@dataclass
class TaskProgress:
    total: int = 0
    completed: int = 0
    waived: int = 0
    pending: int = 0
    overdue: int = 0
    mandatory_total: int = 0
    mandatory_outstanding: int = 0

    @property
    def percent_complete(self) -> int:
        if self.total == 0:
            return 0
        return round(((self.completed + self.waived) / self.total) * 100)

    @property
    def all_mandatory_done(self) -> bool:
        return self.mandatory_outstanding == 0


def compute_progress(db: Session, employee_id) -> TaskProgress:
    tasks = db.scalars(
        select(EmployeeTask).where(EmployeeTask.employee_id == employee_id)
    ).all()

    progress = TaskProgress(total=len(tasks))
    today = date.today()
    for task in tasks:
        if task.status is TaskStatus.COMPLETED:
            progress.completed += 1
        elif task.status is TaskStatus.WAIVED:
            progress.waived += 1
        else:
            progress.pending += 1
            if task.is_overdue(today):
                progress.overdue += 1

        if task.is_mandatory:
            progress.mandatory_total += 1
            if not task.is_closed:
                progress.mandatory_outstanding += 1

    return progress
