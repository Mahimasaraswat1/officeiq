"""Employee profile & invitation schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import InvitationStatus, OnboardingStatus
from app.schemas.user import UserRead, _validate_password_strength


class EmployeeBase(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    work_email: EmailStr
    personal_email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20)
    date_of_birth: date | None = None

    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    postal_code: str | None = Field(default=None, max_length=16)
    country: str | None = Field(default="India", max_length=80)

    department: str | None = Field(default=None, max_length=80)
    designation: str | None = Field(default=None, max_length=80)
    date_of_joining: date | None = None
    reporting_manager: str | None = Field(default=None, max_length=150)


class EmployeeCreate(EmployeeBase):
    """HR-initiated profile creation. `employee_code` is generated when omitted."""

    employee_code: str | None = Field(default=None, max_length=32)
    notes: str | None = None
    send_invite: bool = Field(
        default=True, description="Email an onboarding invite immediately on creation"
    )


class EmployeeUpdate(BaseModel):
    """HR/Admin partial update. Every field is optional."""

    first_name: str | None = Field(default=None, min_length=1, max_length=80)
    last_name: str | None = Field(default=None, min_length=1, max_length=80)
    personal_email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=20)
    date_of_birth: date | None = None

    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    postal_code: str | None = Field(default=None, max_length=16)
    country: str | None = Field(default=None, max_length=80)

    department: str | None = Field(default=None, max_length=80)
    designation: str | None = Field(default=None, max_length=80)
    date_of_joining: date | None = None
    reporting_manager: str | None = Field(default=None, max_length=150)

    onboarding_status: OnboardingStatus | None = None
    notes: str | None = None


class EmployeeSelfUpdate(BaseModel):
    """Fields an employee may edit on their own profile (PRD A.7.10)."""

    phone: str | None = Field(default=None, max_length=20)
    date_of_birth: date | None = None
    personal_email: EmailStr | None = None
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    postal_code: str | None = Field(default=None, max_length=16)
    country: str | None = Field(default=None, max_length=80)


class EmployeeRead(EmployeeBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_code: str
    user_id: uuid.UUID | None = None
    onboarding_status: OnboardingStatus
    onboarding_completed_at: datetime | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class EmployeeSummary(BaseModel):
    """Trimmed shape used by the HR list view."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_code: str
    first_name: str
    last_name: str
    work_email: EmailStr
    department: str | None = None
    designation: str | None = None
    onboarding_status: OnboardingStatus
    date_of_joining: date | None = None
    created_at: datetime


# --- Invitations -----------------------------------------------------------


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    employee_id: uuid.UUID
    email: EmailStr
    status: InvitationStatus
    expires_at: datetime
    accepted_at: datetime | None = None
    created_at: datetime


class InvitationPreview(BaseModel):
    """Returned by the public token-check endpoint so the signup page can pre-fill."""

    email: EmailStr
    first_name: str
    last_name: str
    employee_code: str
    department: str | None = None
    designation: str | None = None
    expires_at: datetime


class AcceptInvitationRequest(BaseModel):
    token: str
    password: str
    phone: str | None = Field(default=None, max_length=20)

    _check_password = field_validator("password")(_validate_password_strength)


class AcceptInvitationResponse(BaseModel):
    message: str
    user: UserRead
    employee: EmployeeRead
