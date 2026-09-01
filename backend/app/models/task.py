"""Task/training catalogue, HR-editable assignment rules, and assigned tasks.

Rules live in the database rather than in code so HR can change onboarding
policy without a deploy (PRD A.7.5 / B.4.5).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.core.database import Base
from app.core.types import TZDateTime
from app.models.employee import Employee
from app.models.enums import DocumentType, TaskCategory, TaskStatus
from app.models.user import User
from app.core.security import today_utc

task_category_enum = SAEnum(
    TaskCategory, name="task_category", values_callable=lambda e: [m.value for m in e]
)
task_status_enum = SAEnum(
    TaskStatus, name="task_status", values_callable=lambda e: [m.value for m in e]
)
document_type_enum_ref = SAEnum(
    DocumentType, name="document_type", values_callable=lambda e: [m.value for m in e],
    create_type=False,  # already created by migration 0002
)


class TaskTemplate(Base):
    """A reusable onboarding item HR can assign via rules."""

    __tablename__ = "task_templates"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[TaskCategory] = mapped_column(
        task_category_enum, nullable=False, index=True
    )

    # Days after the joining date (or assignment date, if no joining date is set).
    default_due_days: Mapped[int | None] = mapped_column(Integer)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # For training modules and policy documents.
    resource_url: Mapped[str | None] = mapped_column(String(512))
    estimated_minutes: Mapped[int | None] = mapped_column(Integer)

    # For DOCUMENT_CHECKLIST items: completing this means uploading and having
    # this document type approved, so the item can close itself.
    required_document_type: Mapped[DocumentType | None] = mapped_column(document_type_enum_ref)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    rule_items: Mapped[list["AssignmentRuleItem"]] = relationship(
        back_populates="template", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<TaskTemplate {self.code} {self.title!r}>"


class AssignmentRule(Base):
    """Maps employee attributes to a set of task templates.

    A NULL match column means "any". Every active rule whose conditions match is
    applied and the resulting templates are unioned — union rather than
    first-match-wins, so a department rule and a designation rule compose the way
    HR expects instead of one silently suppressing the other.
    """

    __tablename__ = "assignment_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # --- Match conditions (NULL = matches anything) ------------------------
    department: Mapped[str | None] = mapped_column(String(80), index=True)
    designation: Mapped[str | None] = mapped_column(String(80))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    # Display/ordering only — it does not make rules override one another.
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    items: Mapped[list["AssignmentRuleItem"]] = relationship(
        back_populates="rule", cascade="all, delete-orphan"
    )

    @property
    def matches_everyone(self) -> bool:
        return self.department is None and self.designation is None

    def matches(self, employee: Employee) -> bool:
        """Case-insensitive match; a NULL condition matches anything."""
        if self.department is not None:
            if not employee.department:
                return False
            if employee.department.strip().lower() != self.department.strip().lower():
                return False
        if self.designation is not None:
            if not employee.designation:
                return False
            if employee.designation.strip().lower() != self.designation.strip().lower():
                return False
        return True

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<AssignmentRule {self.name!r}>"


class AssignmentRuleItem(Base):
    """One template attached to a rule, with optional per-rule overrides."""

    __tablename__ = "assignment_rule_items"
    __table_args__ = (
        UniqueConstraint("rule_id", "template_id", name="uq_rule_template"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("assignment_rules.id", ondelete="CASCADE"), index=True, nullable=False
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("task_templates.id", ondelete="CASCADE"), index=True, nullable=False
    )

    due_days_override: Mapped[int | None] = mapped_column(Integer)
    is_mandatory_override: Mapped[bool | None] = mapped_column(Boolean)

    rule: Mapped[AssignmentRule] = relationship(back_populates="items")
    template: Mapped[TaskTemplate] = relationship(back_populates="rule_items")


class EmployeeTask(Base):
    """A task actually assigned to an employee.

    Title/description/category are snapshotted from the template at assignment
    time so that later edits to a template never rewrite an employee's history.
    """

    __tablename__ = "employee_tasks"
    __table_args__ = (
        # Prevents the engine from assigning the same template twice.
        UniqueConstraint("employee_id", "template_id", name="uq_employee_template"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # NULL for a manually added, one-off task.
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("task_templates.id", ondelete="SET NULL"), index=True
    )
    # Which rule produced this, kept for traceability.
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("assignment_rules.id", ondelete="SET NULL")
    )

    # --- Snapshot ----------------------------------------------------------
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category: Mapped[TaskCategory] = mapped_column(
        task_category_enum, nullable=False, index=True
    )
    resource_url: Mapped[str | None] = mapped_column(String(512))
    required_document_type: Mapped[DocumentType | None] = mapped_column(document_type_enum_ref)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- State -------------------------------------------------------------
    status: Mapped[TaskStatus] = mapped_column(
        task_status_enum, default=TaskStatus.PENDING, nullable=False, index=True
    )
    due_date: Mapped[date | None] = mapped_column(Date, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    completed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    waiver_reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    # NULL when the rule engine assigned it rather than a person.
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    employee: Mapped[Employee] = relationship()
    template: Mapped[TaskTemplate | None] = relationship()
    rule: Mapped[AssignmentRule | None] = relationship()
    completed_by: Mapped[User | None] = relationship(foreign_keys=[completed_by_id])
    assigned_by: Mapped[User | None] = relationship(foreign_keys=[assigned_by_id])

    @property
    def is_closed(self) -> bool:
        """Completed or waived — either way it no longer blocks onboarding."""
        return self.status in (TaskStatus.COMPLETED, TaskStatus.WAIVED)

    def is_overdue(self, today: date | None = None) -> bool:
        if self.is_closed or self.due_date is None:
            return False
        return self.due_date < (today or today_utc())

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<EmployeeTask {self.title!r} {self.status.value}>"
