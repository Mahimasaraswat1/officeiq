"""Rule evaluation and the assignment engine (PRD A.7.5 / B.4.5)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.models.employee import Employee
from app.models.enums import DocumentType, TaskCategory, TaskStatus
from app.models.task import AssignmentRule, AssignmentRuleItem, EmployeeTask, TaskTemplate
from app.services.assignment import (
    assign_tasks,
    compute_progress,
    preview_assignment,
    resolve_templates,
)


def make_template(db, code, **kwargs) -> TaskTemplate:
    template = TaskTemplate(
        code=code,
        title=kwargs.pop("title", code.replace("_", " ").title()),
        category=kwargs.pop("category", TaskCategory.TASK),
        **kwargs,
    )
    db.add(template)
    db.flush()
    return template


def make_rule(db, name, templates, *, department=None, designation=None, **kwargs) -> AssignmentRule:
    rule = AssignmentRule(
        name=name, department=department, designation=designation, **kwargs
    )
    db.add(rule)
    db.flush()
    for entry in templates:
        template, overrides = (entry, {}) if isinstance(entry, TaskTemplate) else entry
        db.add(AssignmentRuleItem(rule_id=rule.id, template_id=template.id, **overrides))
    db.flush()
    return rule


def make_employee(db, **kwargs) -> Employee:
    employee = Employee(
        employee_code=kwargs.pop("employee_code", "EMP9001"),
        first_name=kwargs.pop("first_name", "Ananya"),
        last_name=kwargs.pop("last_name", "Sharma"),
        work_email=kwargs.pop("work_email", "engine.test@example.com"),
        **kwargs,
    )
    db.add(employee)
    db.flush()
    return employee


# --- Rule matching ---------------------------------------------------------


def test_a_rule_with_no_conditions_matches_everyone(db):
    template = make_template(db, "BASE")
    make_rule(db, "All", [template])

    for employee_kwargs in (
        {"department": "Engineering", "work_email": "a@example.com", "employee_code": "E1"},
        {"department": None, "work_email": "b@example.com", "employee_code": "E2"},
        {"department": "Finance", "work_email": "c@example.com", "employee_code": "E3"},
    ):
        employee = make_employee(db, **employee_kwargs)
        assert [i.template.code for i in resolve_templates(db, employee)] == ["BASE"]


def test_department_rule_only_matches_that_department(db):
    base = make_template(db, "BASE")
    eng = make_template(db, "ENG_ONLY")
    make_rule(db, "All", [base])
    make_rule(db, "Engineering", [eng], department="Engineering")

    engineer = make_employee(db, department="Engineering", work_email="e@example.com",
                             employee_code="E1")
    finance = make_employee(db, department="Finance", work_email="f@example.com",
                            employee_code="E2")

    assert {i.template.code for i in resolve_templates(db, engineer)} == {"BASE", "ENG_ONLY"}
    assert {i.template.code for i in resolve_templates(db, finance)} == {"BASE"}


def test_department_matching_is_case_insensitive(db):
    template = make_template(db, "ENG")
    make_rule(db, "Engineering", [template], department="Engineering")

    employee = make_employee(db, department="  engineering  ", work_email="e@example.com")
    assert [i.template.code for i in resolve_templates(db, employee)] == ["ENG"]


def test_designation_rule_matches_on_designation(db):
    template = make_template(db, "MGR")
    make_rule(db, "Managers", [template], designation="Engineering Manager")

    manager = make_employee(db, designation="Engineering Manager", work_email="m@example.com")
    engineer = make_employee(db, designation="Software Engineer", work_email="s@example.com",
                             employee_code="E2")

    assert [i.template.code for i in resolve_templates(db, manager)] == ["MGR"]
    assert resolve_templates(db, engineer) == []


def test_rule_requiring_department_does_not_match_an_employee_without_one(db):
    template = make_template(db, "ENG")
    make_rule(db, "Engineering", [template], department="Engineering")

    employee = make_employee(db, department=None, work_email="none@example.com")
    assert resolve_templates(db, employee) == []


def test_inactive_rules_are_ignored(db):
    template = make_template(db, "OFF")
    make_rule(db, "Disabled", [template], is_active=False)

    employee = make_employee(db, work_email="x@example.com")
    assert resolve_templates(db, employee) == []


def test_inactive_templates_are_ignored(db):
    template = make_template(db, "OFF", is_active=False)
    make_rule(db, "All", [template])

    employee = make_employee(db, work_email="x@example.com")
    assert resolve_templates(db, employee) == []


# --- Union semantics -------------------------------------------------------


def test_multiple_matching_rules_are_unioned_not_overridden(db):
    """A department rule must add to the baseline, not replace it."""
    base_a = make_template(db, "BASE_A")
    base_b = make_template(db, "BASE_B")
    eng = make_template(db, "ENG")

    make_rule(db, "All", [base_a, base_b], priority=10)
    make_rule(db, "Engineering", [eng], department="Engineering", priority=20)

    employee = make_employee(db, department="Engineering", work_email="e@example.com")
    codes = {i.template.code for i in resolve_templates(db, employee)}
    assert codes == {"BASE_A", "BASE_B", "ENG"}


def test_a_template_selected_by_two_rules_yields_one_task(db):
    shared = make_template(db, "SHARED")
    make_rule(db, "All", [shared])
    make_rule(db, "Engineering", [shared], department="Engineering")

    employee = make_employee(db, department="Engineering", work_email="e@example.com")
    resolved = resolve_templates(db, employee)
    assert len(resolved) == 1


def test_conflicting_rules_keep_the_stricter_setting(db):
    """Optional-vs-mandatory and later-vs-earlier must resolve to the stricter."""
    template = make_template(db, "SHARED", default_due_days=30, is_mandatory=False)

    make_rule(db, "Lenient", [(template, {"due_days_override": 30,
                                          "is_mandatory_override": False})])
    make_rule(db, "Strict", [(template, {"due_days_override": 7,
                                         "is_mandatory_override": True})],
              department="Engineering")

    employee = make_employee(db, department="Engineering", work_email="e@example.com")
    resolved = resolve_templates(db, employee)

    assert len(resolved) == 1
    assert resolved[0].due_days == 7          # earlier deadline wins
    assert resolved[0].is_mandatory is True   # mandatory wins over optional


def test_rule_item_overrides_template_defaults(db):
    template = make_template(db, "T", default_due_days=30, is_mandatory=True)
    make_rule(db, "Override", [(template, {"due_days_override": 3,
                                           "is_mandatory_override": False})])

    employee = make_employee(db, work_email="e@example.com")
    resolved = resolve_templates(db, employee)[0]
    assert resolved.due_days == 3
    assert resolved.is_mandatory is False


# --- Assignment ------------------------------------------------------------


def test_assignment_creates_tasks_with_a_snapshot(db):
    template = make_template(db, "T", title="Original title", description="Original text")
    make_rule(db, "All", [template])
    employee = make_employee(db, work_email="e@example.com")

    result = assign_tasks(db, employee=employee)
    db.commit()

    assert result.count == 1
    task = db.scalar(select(EmployeeTask))
    assert task.title == "Original title"

    # Editing the template must not rewrite the already-assigned task.
    template.title = "Renamed"
    template.description = "Changed"
    db.commit()
    db.refresh(task)
    assert task.title == "Original title"
    assert task.description == "Original text"


def test_assignment_is_idempotent(db):
    template = make_template(db, "T")
    make_rule(db, "All", [template])
    employee = make_employee(db, work_email="e@example.com")

    first = assign_tasks(db, employee=employee)
    db.commit()
    second = assign_tasks(db, employee=employee)
    db.commit()

    assert first.count == 1
    assert second.count == 0
    assert second.skipped_existing == ["T"]
    assert db.scalar(select(EmployeeTask).where(EmployeeTask.employee_id == employee.id))
    assert len(db.scalars(select(EmployeeTask)).all()) == 1


def test_due_date_is_relative_to_the_joining_date(db):
    template = make_template(db, "T", default_due_days=7)
    make_rule(db, "All", [template])
    joining = date(2026, 9, 1)
    employee = make_employee(db, work_email="e@example.com", date_of_joining=joining)

    assign_tasks(db, employee=employee)
    db.commit()

    task = db.scalar(select(EmployeeTask))
    assert task.due_date == joining + timedelta(days=7)


def test_due_date_falls_back_to_today_without_a_joining_date(db):
    template = make_template(db, "T", default_due_days=5)
    make_rule(db, "All", [template])
    employee = make_employee(db, work_email="e@example.com", date_of_joining=None)

    assign_tasks(db, employee=employee)
    db.commit()

    task = db.scalar(select(EmployeeTask))
    assert task.due_date == date.today() + timedelta(days=5)


def test_template_without_due_days_produces_no_due_date(db):
    template = make_template(db, "T", default_due_days=None)
    make_rule(db, "All", [template])
    employee = make_employee(db, work_email="e@example.com")

    assign_tasks(db, employee=employee)
    db.commit()
    assert db.scalar(select(EmployeeTask)).due_date is None


def test_assignment_records_which_rule_produced_each_task(db):
    template = make_template(db, "ENG")
    rule = make_rule(db, "Engineering", [template], department="Engineering")
    employee = make_employee(db, department="Engineering", work_email="e@example.com")

    assign_tasks(db, employee=employee)
    db.commit()

    task = db.scalar(select(EmployeeTask))
    assert task.rule_id == rule.id


def test_assigning_with_no_matching_rules_is_a_no_op(db):
    employee = make_employee(db, work_email="e@example.com")
    result = assign_tasks(db, employee=employee)
    db.commit()
    assert result.count == 0


# --- Preview ---------------------------------------------------------------


def test_preview_reports_what_would_be_assigned(db):
    base = make_template(db, "BASE")
    eng = make_template(db, "ENG")
    make_rule(db, "All", [base])
    make_rule(db, "Engineering", [eng], department="Engineering")

    matched, resolved = preview_assignment(db, department="Engineering", designation=None)

    assert {r.name for r in matched} == {"All", "Engineering"}
    assert {i.template.code for i in resolved} == {"BASE", "ENG"}


def test_preview_does_not_create_anything(db):
    template = make_template(db, "T")
    make_rule(db, "All", [template])

    preview_assignment(db, department="Engineering", designation=None)
    db.commit()

    assert db.scalars(select(EmployeeTask)).all() == []
    # The probe employee must not be persisted either.
    assert db.scalar(select(Employee).where(Employee.employee_code == "PREVIEW")) is None


# --- Progress --------------------------------------------------------------


def test_progress_counts_and_percentage(db):
    templates = [make_template(db, f"T{i}") for i in range(4)]
    make_rule(db, "All", templates)
    employee = make_employee(db, work_email="e@example.com")
    assign_tasks(db, employee=employee)
    db.commit()

    tasks = db.scalars(select(EmployeeTask)).all()
    tasks[0].status = TaskStatus.COMPLETED
    tasks[1].status = TaskStatus.WAIVED
    db.commit()

    progress = compute_progress(db, employee.id)
    assert progress.total == 4
    assert progress.completed == 1
    assert progress.waived == 1
    assert progress.pending == 2
    # Waived counts as closed for percentage purposes.
    assert progress.percent_complete == 50


def test_waived_tasks_do_not_block_completion(db):
    template = make_template(db, "T", is_mandatory=True)
    make_rule(db, "All", [template])
    employee = make_employee(db, work_email="e@example.com")
    assign_tasks(db, employee=employee)
    db.commit()

    assert compute_progress(db, employee.id).all_mandatory_done is False

    db.scalar(select(EmployeeTask)).status = TaskStatus.WAIVED
    db.commit()

    assert compute_progress(db, employee.id).all_mandatory_done is True


def test_optional_tasks_never_block_completion(db):
    optional = make_template(db, "OPT", is_mandatory=False)
    make_rule(db, "All", [optional])
    employee = make_employee(db, work_email="e@example.com")
    assign_tasks(db, employee=employee)
    db.commit()

    progress = compute_progress(db, employee.id)
    assert progress.mandatory_total == 0
    assert progress.all_mandatory_done is True


def test_overdue_tasks_are_counted(db):
    template = make_template(db, "T", default_due_days=0)
    make_rule(db, "All", [template])
    employee = make_employee(
        db, work_email="e@example.com", date_of_joining=date.today() - timedelta(days=10)
    )
    assign_tasks(db, employee=employee)
    db.commit()

    progress = compute_progress(db, employee.id)
    assert progress.overdue == 1

    db.scalar(select(EmployeeTask)).status = TaskStatus.COMPLETED
    db.commit()
    # A completed task is never overdue, however late it was.
    assert compute_progress(db, employee.id).overdue == 0


def test_progress_of_an_employee_with_no_tasks(db):
    employee = make_employee(db, work_email="e@example.com")
    db.commit()

    progress = compute_progress(db, employee.id)
    assert progress.total == 0
    assert progress.percent_complete == 0
    assert progress.all_mandatory_done is True
