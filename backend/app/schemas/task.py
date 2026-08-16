"""Task template, assignment rule, and employee task schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import DocumentType, TaskCategory, TaskStatus

WAIVER_REASON_MIN_LENGTH = 10


# --- Task templates --------------------------------------------------------


class TaskTemplateBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category: TaskCategory = TaskCategory.TASK
    default_due_days: int | None = Field(default=None, ge=0, le=3650)
    is_mandatory: bool = True
    is_active: bool = True
    resource_url: str | None = Field(default=None, max_length=512)
    estimated_minutes: int | None = Field(default=None, ge=0, le=100_000)
    required_document_type: DocumentType | None = None


class TaskTemplateCreate(TaskTemplateBase):
    code: str = Field(
        min_length=2,
        max_length=64,
        description="Stable identifier, e.g. IT_LAPTOP. Uppercased automatically.",
    )

    @field_validator("code")
    @classmethod
    def _normalise_code(cls, value: str) -> str:
        cleaned = value.strip().upper().replace(" ", "_")
        if not cleaned.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Code may contain only letters, digits, hyphens, and underscores.")
        return cleaned


class TaskTemplateUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    category: TaskCategory | None = None
    default_due_days: int | None = Field(default=None, ge=0, le=3650)
    is_mandatory: bool | None = None
    is_active: bool | None = None
    resource_url: str | None = Field(default=None, max_length=512)
    estimated_minutes: int | None = Field(default=None, ge=0, le=100_000)
    required_document_type: DocumentType | None = None


class TaskTemplateRead(TaskTemplateBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    created_at: datetime
    updated_at: datetime


# --- Assignment rules ------------------------------------------------------


class RuleItemInput(BaseModel):
    template_id: uuid.UUID
    due_days_override: int | None = Field(default=None, ge=0, le=3650)
    is_mandatory_override: bool | None = None


class RuleItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template_id: uuid.UUID
    due_days_override: int | None = None
    is_mandatory_override: bool | None = None
    template: TaskTemplateRead | None = None


class AssignmentRuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    department: str | None = Field(
        default=None, max_length=80, description="Leave empty to match any department"
    )
    designation: str | None = Field(
        default=None, max_length=80, description="Leave empty to match any designation"
    )
    is_active: bool = True
    priority: int = Field(default=100, ge=0, le=10_000)

    @field_validator("department", "designation")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        # An empty string from a form must mean "any", not "match the empty string".
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AssignmentRuleCreate(AssignmentRuleBase):
    items: list[RuleItemInput] = Field(default_factory=list)


class AssignmentRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    department: str | None = Field(default=None, max_length=80)
    designation: str | None = Field(default=None, max_length=80)
    is_active: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10_000)
    # When provided, replaces the rule's item list wholesale.
    items: list[RuleItemInput] | None = None

    @field_validator("department", "designation")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class AssignmentRuleRead(AssignmentRuleBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    items: list[RuleItemRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RulePreviewRequest(BaseModel):
    department: str | None = None
    designation: str | None = None


class RulePreviewResponse(BaseModel):
    """What the engine would assign — lets HR check a rule before saving it."""

    matched_rules: list[str] = Field(default_factory=list)
    templates: list[TaskTemplateRead] = Field(default_factory=list)
    total: int = 0


# --- Employee tasks --------------------------------------------------------


class EmployeeTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    template_id: uuid.UUID | None = None
    rule_id: uuid.UUID | None = None

    title: str
    description: str | None = None
    category: TaskCategory
    resource_url: str | None = None
    required_document_type: DocumentType | None = None
    is_mandatory: bool

    status: TaskStatus
    due_date: date | None = None
    completed_at: datetime | None = None
    waiver_reason: str | None = None
    notes: str | None = None
    created_at: datetime


class EmployeeTaskOut(EmployeeTaskRead):
    is_overdue: bool = False

    @classmethod
    def from_model(cls, task) -> "EmployeeTaskOut":
        return cls(
            **EmployeeTaskRead.model_validate(task).model_dump(),
            is_overdue=task.is_overdue(),
        )


class TaskStatusUpdate(BaseModel):
    status: TaskStatus
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("status")
    @classmethod
    def _not_waived_here(cls, value: TaskStatus) -> TaskStatus:
        # Waiving needs a reason, so it has its own endpoint.
        if value is TaskStatus.WAIVED:
            raise ValueError("Use the waive endpoint to waive a task — a reason is required.")
        return value


class TaskWaiveRequest(BaseModel):
    reason: str = Field(min_length=WAIVER_REASON_MIN_LENGTH, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _meaningful(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < WAIVER_REASON_MIN_LENGTH:
            raise ValueError(
                f"Please give a reason of at least {WAIVER_REASON_MIN_LENGTH} characters."
            )
        return cleaned


class ManualTaskCreate(BaseModel):
    """A one-off task outside the rule engine."""

    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category: TaskCategory = TaskCategory.TASK
    due_date: date | None = None
    is_mandatory: bool = False
    resource_url: str | None = Field(default=None, max_length=512)


class TaskProgressRead(BaseModel):
    total: int
    completed: int
    waived: int
    pending: int
    overdue: int
    mandatory_total: int
    mandatory_outstanding: int
    percent_complete: int
    all_mandatory_done: bool


class AssignmentRunResult(BaseModel):
    assigned_count: int
    assigned: list[str] = Field(default_factory=list)
    skipped_existing: list[str] = Field(default_factory=list)
    matched_rules: list[str] = Field(default_factory=list)
    message: str
