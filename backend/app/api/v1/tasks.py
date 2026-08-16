"""Task templates, HR-editable assignment rules, and employee tasks (PRD A.7.5)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession, HrUser
from app.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.core.security import utcnow
from app.models.employee import Employee
from app.models.enums import AuditAction, TaskCategory, TaskStatus, UserRole
from app.models.task import AssignmentRule, AssignmentRuleItem, EmployeeTask, TaskTemplate
from app.models.user import User
from app.schemas.common import Message
from app.schemas.task import (
    AssignmentRuleCreate,
    AssignmentRuleRead,
    AssignmentRuleUpdate,
    AssignmentRunResult,
    EmployeeTaskOut,
    ManualTaskCreate,
    RulePreviewRequest,
    RulePreviewResponse,
    TaskProgressRead,
    TaskStatusUpdate,
    TaskTemplateCreate,
    TaskTemplateRead,
    TaskTemplateUpdate,
    TaskWaiveRequest,
)
from app.services.assignment import (
    assign_tasks,
    compute_progress,
    preview_assignment,
    sync_document_checklist,
)
from app.services.audit import record_audit

router = APIRouter(tags=["Tasks & Training"])


def _get_employee_or_404(db: DbSession, employee_id: uuid.UUID) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError("Employee not found.")
    return employee


def _assert_can_access(employee: Employee, user: User) -> None:
    if user.role in (UserRole.ADMIN, UserRole.HR):
        return
    if employee.user_id != user.id:
        raise PermissionDeniedError("You can only access your own tasks.")


def _progress_read(progress) -> TaskProgressRead:
    return TaskProgressRead(
        total=progress.total,
        completed=progress.completed,
        waived=progress.waived,
        pending=progress.pending,
        overdue=progress.overdue,
        mandatory_total=progress.mandatory_total,
        mandatory_outstanding=progress.mandatory_outstanding,
        percent_complete=progress.percent_complete,
        all_mandatory_done=progress.all_mandatory_done,
    )


# --- Task templates (HR/Admin) ---------------------------------------------


@router.get(
    "/task-templates",
    response_model=list[TaskTemplateRead],
    summary="List task/training templates",
)
def list_templates(
    db: DbSession,
    _: HrUser,
    category: TaskCategory | None = None,
    include_inactive: bool = False,
) -> list[TaskTemplateRead]:
    filters = []
    if category:
        filters.append(TaskTemplate.category == category)
    if not include_inactive:
        filters.append(TaskTemplate.is_active.is_(True))

    rows = db.scalars(
        select(TaskTemplate).where(*filters).order_by(TaskTemplate.category, TaskTemplate.code)
    ).all()
    return [TaskTemplateRead.model_validate(row) for row in rows]


@router.post(
    "/task-templates",
    response_model=TaskTemplateRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task/training template",
)
def create_template(
    payload: TaskTemplateCreate, request: Request, db: DbSession, actor: HrUser
) -> TaskTemplateRead:
    if db.scalar(select(TaskTemplate.id).where(TaskTemplate.code == payload.code)):
        raise ConflictError(f"A template with code {payload.code} already exists.")

    if (
        payload.category is TaskCategory.DOCUMENT_CHECKLIST
        and payload.required_document_type is None
    ):
        raise ValidationError(
            "A document checklist item needs a required_document_type so it can "
            "complete itself when the document is approved."
        )

    template = TaskTemplate(**payload.model_dump(), created_by_id=actor.id)
    db.add(template)
    db.flush()

    record_audit(
        db,
        action=AuditAction.TASK_TEMPLATE_CREATED,
        actor=actor,
        entity_type="task_template",
        entity_id=template.id,
        detail={"code": template.code, "title": template.title},
        request=request,
    )
    db.commit()
    db.refresh(template)
    return TaskTemplateRead.model_validate(template)


@router.patch(
    "/task-templates/{template_id}",
    response_model=TaskTemplateRead,
    summary="Update a template",
)
def update_template(
    template_id: uuid.UUID,
    payload: TaskTemplateUpdate,
    request: Request,
    db: DbSession,
    actor: HrUser,
) -> TaskTemplateRead:
    template = db.get(TaskTemplate, template_id)
    if template is None:
        raise NotFoundError("Task template not found.")

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(template, field, value)

    record_audit(
        db,
        action=AuditAction.TASK_TEMPLATE_UPDATED,
        actor=actor,
        entity_type="task_template",
        entity_id=template.id,
        detail={"code": template.code, "fields": sorted(changes.keys())},
        request=request,
    )
    db.commit()
    db.refresh(template)
    return TaskTemplateRead.model_validate(template)


@router.delete(
    "/task-templates/{template_id}",
    response_model=Message,
    summary="Delete a template (Admin)",
)
def delete_template(
    template_id: uuid.UUID, request: Request, db: DbSession, actor: CurrentUser
) -> Message:
    if actor.role is not UserRole.ADMIN:
        raise PermissionDeniedError("Only an administrator can delete templates.")

    template = db.get(TaskTemplate, template_id)
    if template is None:
        raise NotFoundError("Task template not found.")

    # Already-assigned tasks keep their snapshot, so history survives deletion.
    assigned = db.scalar(
        select(EmployeeTask.id).where(EmployeeTask.template_id == template.id)
    )
    if assigned is not None:
        raise ConflictError(
            "This template has already been assigned to employees. "
            "Deactivate it instead so existing tasks keep their history."
        )

    record_audit(
        db,
        action=AuditAction.TASK_TEMPLATE_DELETED,
        actor=actor,
        entity_type="task_template",
        entity_id=template.id,
        detail={"code": template.code, "title": template.title},
        request=request,
    )
    db.delete(template)
    db.commit()
    return Message(message="Template deleted.")


# --- Assignment rules (HR/Admin) -------------------------------------------


def _rule_query():
    return select(AssignmentRule).options(
        selectinload(AssignmentRule.items).selectinload(AssignmentRuleItem.template)
    )


def _replace_items(db: DbSession, rule: AssignmentRule, items) -> None:
    """Swap a rule's template list wholesale, validating every template id."""
    db.query(AssignmentRuleItem).filter(
        AssignmentRuleItem.rule_id == rule.id
    ).delete(synchronize_session=False)

    seen: set[uuid.UUID] = set()
    for item in items:
        if item.template_id in seen:
            continue  # tolerate a duplicated id in the payload
        seen.add(item.template_id)

        if db.get(TaskTemplate, item.template_id) is None:
            raise ValidationError(f"Unknown task template: {item.template_id}")

        db.add(
            AssignmentRuleItem(
                rule_id=rule.id,
                template_id=item.template_id,
                due_days_override=item.due_days_override,
                is_mandatory_override=item.is_mandatory_override,
            )
        )
    db.flush()


@router.get(
    "/assignment-rules",
    response_model=list[AssignmentRuleRead],
    summary="List assignment rules",
)
def list_rules(db: DbSession, _: HrUser, include_inactive: bool = True) -> list[AssignmentRuleRead]:
    query = _rule_query()
    if not include_inactive:
        query = query.where(AssignmentRule.is_active.is_(True))
    rows = db.scalars(
        query.order_by(AssignmentRule.priority, AssignmentRule.created_at)
    ).all()
    return [AssignmentRuleRead.model_validate(row) for row in rows]


@router.post(
    "/assignment-rules",
    response_model=AssignmentRuleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an assignment rule",
)
def create_rule(
    payload: AssignmentRuleCreate, request: Request, db: DbSession, actor: HrUser
) -> AssignmentRuleRead:
    data = payload.model_dump(exclude={"items"})
    rule = AssignmentRule(**data, created_by_id=actor.id)
    db.add(rule)
    db.flush()

    _replace_items(db, rule, payload.items)

    record_audit(
        db,
        action=AuditAction.ASSIGNMENT_RULE_CREATED,
        actor=actor,
        entity_type="assignment_rule",
        entity_id=rule.id,
        detail={
            "name": rule.name,
            "department": rule.department,
            "designation": rule.designation,
            "items": len(payload.items),
        },
        request=request,
    )
    db.commit()

    created = db.scalar(_rule_query().where(AssignmentRule.id == rule.id))
    return AssignmentRuleRead.model_validate(created)


@router.patch(
    "/assignment-rules/{rule_id}",
    response_model=AssignmentRuleRead,
    summary="Update an assignment rule",
)
def update_rule(
    rule_id: uuid.UUID,
    payload: AssignmentRuleUpdate,
    request: Request,
    db: DbSession,
    actor: HrUser,
) -> AssignmentRuleRead:
    rule = db.get(AssignmentRule, rule_id)
    if rule is None:
        raise NotFoundError("Assignment rule not found.")

    changes = payload.model_dump(exclude_unset=True, exclude={"items"})
    for field, value in changes.items():
        setattr(rule, field, value)

    if payload.items is not None:
        _replace_items(db, rule, payload.items)

    record_audit(
        db,
        action=AuditAction.ASSIGNMENT_RULE_UPDATED,
        actor=actor,
        entity_type="assignment_rule",
        entity_id=rule.id,
        detail={
            "name": rule.name,
            "fields": sorted(changes.keys()),
            "items_replaced": payload.items is not None,
        },
        request=request,
    )
    db.commit()

    updated = db.scalar(_rule_query().where(AssignmentRule.id == rule.id))
    return AssignmentRuleRead.model_validate(updated)


@router.delete(
    "/assignment-rules/{rule_id}", response_model=Message, summary="Delete an assignment rule"
)
def delete_rule(
    rule_id: uuid.UUID, request: Request, db: DbSession, actor: HrUser
) -> Message:
    rule = db.get(AssignmentRule, rule_id)
    if rule is None:
        raise NotFoundError("Assignment rule not found.")

    record_audit(
        db,
        action=AuditAction.ASSIGNMENT_RULE_DELETED,
        actor=actor,
        entity_type="assignment_rule",
        entity_id=rule.id,
        detail={"name": rule.name},
        request=request,
    )
    db.delete(rule)
    db.commit()
    return Message(message="Assignment rule deleted. Tasks already assigned are unaffected.")


@router.post(
    "/assignment-rules/preview",
    response_model=RulePreviewResponse,
    summary="Preview what would be assigned for given attributes",
)
def preview_rules(
    payload: RulePreviewRequest, db: DbSession, _: HrUser
) -> RulePreviewResponse:
    matched, resolved = preview_assignment(
        db, department=payload.department, designation=payload.designation
    )
    return RulePreviewResponse(
        matched_rules=[rule.name for rule in matched],
        templates=[TaskTemplateRead.model_validate(item.template) for item in resolved],
        total=len(resolved),
    )


# --- Employee tasks --------------------------------------------------------


@router.post(
    "/employees/{employee_id}/assign-tasks",
    response_model=AssignmentRunResult,
    summary="Run the assignment engine for an employee",
)
def run_assignment(
    employee_id: uuid.UUID, request: Request, db: DbSession, actor: HrUser
) -> AssignmentRunResult:
    employee = _get_employee_or_404(db, employee_id)
    result = assign_tasks(db, employee=employee, actor=actor)
    db.commit()

    return AssignmentRunResult(
        assigned_count=result.count,
        assigned=[t.title for t in result.assigned],
        skipped_existing=result.skipped_existing,
        matched_rules=result.matched_rules,
        message=(
            f"Assigned {result.count} new task(s)."
            if result.count
            else "No new tasks to assign — everything applicable is already assigned."
        ),
    )


@router.get(
    "/employees/{employee_id}/tasks",
    response_model=list[EmployeeTaskOut],
    summary="List an employee's tasks",
)
def list_employee_tasks(
    employee_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    category: TaskCategory | None = None,
    task_status: TaskStatus | None = Query(default=None, alias="status"),
) -> list[EmployeeTaskOut]:
    employee = _get_employee_or_404(db, employee_id)
    _assert_can_access(employee, user)

    # A document approved elsewhere may already satisfy a checklist item.
    if sync_document_checklist(db, employee=employee, actor=None):
        db.commit()

    filters = [EmployeeTask.employee_id == employee.id]
    if category:
        filters.append(EmployeeTask.category == category)
    if task_status:
        filters.append(EmployeeTask.status == task_status)

    rows = db.scalars(
        select(EmployeeTask)
        .where(*filters)
        .order_by(
            EmployeeTask.is_mandatory.desc(),
            EmployeeTask.due_date.is_(None),
            EmployeeTask.due_date,
            EmployeeTask.created_at,
        )
    ).all()
    return [EmployeeTaskOut.from_model(row) for row in rows]


@router.get(
    "/employees/{employee_id}/task-progress",
    response_model=TaskProgressRead,
    summary="Task completion progress for an employee",
)
def task_progress(
    employee_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> TaskProgressRead:
    employee = _get_employee_or_404(db, employee_id)
    _assert_can_access(employee, user)

    if sync_document_checklist(db, employee=employee, actor=None):
        db.commit()

    return _progress_read(compute_progress(db, employee.id))


@router.post(
    "/employees/{employee_id}/tasks",
    response_model=EmployeeTaskOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a one-off task outside the rule engine (HR)",
)
def add_manual_task(
    employee_id: uuid.UUID,
    payload: ManualTaskCreate,
    request: Request,
    db: DbSession,
    actor: HrUser,
) -> EmployeeTaskOut:
    employee = _get_employee_or_404(db, employee_id)

    task = EmployeeTask(
        employee_id=employee.id,
        title=payload.title,
        description=payload.description,
        category=payload.category,
        due_date=payload.due_date,
        is_mandatory=payload.is_mandatory,
        resource_url=payload.resource_url,
        status=TaskStatus.PENDING,
        assigned_by_id=actor.id,
    )
    db.add(task)
    db.flush()

    record_audit(
        db,
        action=AuditAction.TASK_ADDED_MANUALLY,
        actor=actor,
        entity_type="employee_task",
        entity_id=task.id,
        detail={"employee_id": str(employee.id), "title": task.title},
        request=request,
    )
    db.commit()
    db.refresh(task)
    return EmployeeTaskOut.from_model(task)


def _get_task_or_404(db: DbSession, task_id: uuid.UUID) -> EmployeeTask:
    task = db.get(EmployeeTask, task_id)
    if task is None:
        raise NotFoundError("Task not found.")
    return task


@router.patch(
    "/tasks/{task_id}", response_model=EmployeeTaskOut, summary="Update a task's status"
)
def update_task_status(
    task_id: uuid.UUID,
    payload: TaskStatusUpdate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> EmployeeTaskOut:
    task = _get_task_or_404(db, task_id)
    _assert_can_access(task.employee, user)

    if task.status is TaskStatus.WAIVED and user.role not in (UserRole.ADMIN, UserRole.HR):
        raise PermissionDeniedError("Only HR can change a waived task.")

    previous = task.status
    task.status = payload.status
    if payload.notes is not None:
        task.notes = payload.notes

    if payload.status is TaskStatus.COMPLETED:
        task.completed_at = utcnow()
        task.completed_by_id = user.id
        action = AuditAction.TASK_COMPLETED
    else:
        # Reopening clears the completion record so it cannot mislead later.
        task.completed_at = None
        task.completed_by_id = None
        task.waiver_reason = None
        action = AuditAction.TASK_REOPENED if previous is not TaskStatus.PENDING else None

    if action is not None:
        record_audit(
            db,
            action=action,
            actor=user,
            entity_type="employee_task",
            entity_id=task.id,
            detail={
                "employee_id": str(task.employee_id),
                "title": task.title,
                "from": previous.value,
                "to": task.status.value,
            },
            request=request,
        )
    db.commit()
    db.refresh(task)
    return EmployeeTaskOut.from_model(task)


@router.post(
    "/tasks/{task_id}/waive",
    response_model=EmployeeTaskOut,
    summary="Waive a task with a mandatory reason (HR)",
)
def waive_task(
    task_id: uuid.UUID,
    payload: TaskWaiveRequest,
    request: Request,
    db: DbSession,
    actor: HrUser,
) -> EmployeeTaskOut:
    task = _get_task_or_404(db, task_id)

    if task.status is TaskStatus.COMPLETED:
        raise ConflictError("This task is already completed and does not need waiving.")

    previous = task.status
    task.status = TaskStatus.WAIVED
    task.waiver_reason = payload.reason
    task.completed_at = utcnow()
    task.completed_by_id = actor.id

    record_audit(
        db,
        action=AuditAction.TASK_WAIVED,
        actor=actor,
        entity_type="employee_task",
        entity_id=task.id,
        detail={
            "employee_id": str(task.employee_id),
            "title": task.title,
            "from": previous.value,
            "reason": payload.reason,
        },
        request=request,
    )
    db.commit()
    db.refresh(task)
    return EmployeeTaskOut.from_model(task)


@router.delete("/tasks/{task_id}", response_model=Message, summary="Delete a task (HR)")
def delete_task(
    task_id: uuid.UUID, request: Request, db: DbSession, actor: HrUser
) -> Message:
    task = _get_task_or_404(db, task_id)

    record_audit(
        db,
        action=AuditAction.TASK_TEMPLATE_DELETED,
        actor=actor,
        entity_type="employee_task",
        entity_id=task.id,
        detail={"employee_id": str(task.employee_id), "title": task.title},
        request=request,
    )
    db.delete(task)
    db.commit()
    return Message(message="Task removed.")


# --- Self-service ----------------------------------------------------------


@router.get("/my-tasks", response_model=list[EmployeeTaskOut], summary="My own tasks")
def my_tasks(db: DbSession, user: CurrentUser) -> list[EmployeeTaskOut]:
    employee = db.scalar(select(Employee).where(Employee.user_id == user.id))
    if employee is None:
        raise NotFoundError("No employee record is linked to this account.")
    return list_employee_tasks(employee.id, db, user, None, None)


@router.get("/my-task-progress", response_model=TaskProgressRead, summary="My own progress")
def my_task_progress(db: DbSession, user: CurrentUser) -> TaskProgressRead:
    employee = db.scalar(select(Employee).where(Employee.user_id == user.id))
    if employee is None:
        raise NotFoundError("No employee record is linked to this account.")
    return task_progress(employee.id, db, user)
