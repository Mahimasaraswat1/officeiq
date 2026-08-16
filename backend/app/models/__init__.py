"""Import every model here so Alembic autogenerate and Base.metadata see them."""

from app.models.audit import AuditLog
from app.models.document import Document, ExtractedField, ResumeProfile
from app.models.employee import Employee, Invitation
from app.models.enums import (
    AuditAction,
    ChatOutcome,
    ChatRole,
    DocumentStatus,
    DocumentType,
    ExtractionSource,
    FaceMatchStatus,
    InvitationStatus,
    KnowledgeCategory,
    KnowledgeStatus,
    NotificationType,
    OnboardingStatus,
    TaskCategory,
    TaskStatus,
    UserRole,
    VerificationCheckType,
    VerificationStatus,
)
from app.models.knowledge import (
    ChatConversation,
    ChatMessage,
    KnowledgeChunk,
    KnowledgeDocument,
)
from app.models.notification import Notification
from app.models.task import (
    AssignmentRule,
    AssignmentRuleItem,
    EmployeeTask,
    TaskTemplate,
)
from app.models.user import PasswordResetToken, RefreshToken, User
from app.models.verification import FaceMatch, VerificationCheck

__all__ = [
    "AssignmentRule",
    "ChatConversation",
    "ChatMessage",
    "ChatOutcome",
    "ChatRole",
    "AssignmentRuleItem",
    "AuditAction",
    "AuditLog",
    "Document",
    "DocumentStatus",
    "DocumentType",
    "Employee",
    "EmployeeTask",
    "ExtractedField",
    "ExtractionSource",
    "FaceMatch",
    "FaceMatchStatus",
    "Invitation",
    "InvitationStatus",
    "KnowledgeCategory",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeStatus",
    "Notification",
    "NotificationType",
    "OnboardingStatus",
    "PasswordResetToken",
    "RefreshToken",
    "ResumeProfile",
    "TaskCategory",
    "TaskStatus",
    "TaskTemplate",
    "User",
    "UserRole",
    "VerificationCheck",
    "VerificationCheckType",
    "VerificationStatus",
]
