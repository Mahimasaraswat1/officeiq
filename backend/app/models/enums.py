"""Shared enumerations. Values are stored in the DB, so keep them stable."""

from enum import Enum


class UserRole(str, Enum):
    ADMIN = "admin"
    HR = "hr"
    EMPLOYEE = "employee"


class OnboardingStatus(str, Enum):
    """Lifecycle of an employee's onboarding journey (PRD A.6)."""

    INVITED = "invited"                        # profile created, invite sent
    REGISTERED = "registered"                  # employee accepted invite, account active
    DOCUMENTS_PENDING = "documents_pending"    # awaiting uploads          (Phase 2)
    DOCUMENTS_SUBMITTED = "documents_submitted"  # uploads done            (Phase 2)
    UNDER_REVIEW = "under_review"              # HR reviewing              (Phase 3)
    TASKS_ASSIGNED = "tasks_assigned"          # tasks/training assigned   (Phase 4)
    COMPLETE = "complete"                      # onboarding complete
    REJECTED = "rejected"                      # rejected / withdrawn


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class DocumentType(str, Enum):
    """Document categories accepted during onboarding (PRD A.7.3)."""

    AADHAAR = "aadhaar"
    PAN = "pan"
    RESUME = "resume"
    CERTIFICATE = "certificate"
    PHOTO = "photo"
    OTHER = "other"


class DocumentStatus(str, Enum):
    """Processing lifecycle of an uploaded document."""

    UPLOADED = "uploaded"        # stored, extraction not started
    PROCESSING = "processing"    # OCR / parsing in flight
    EXTRACTED = "extracted"      # extraction finished, awaiting HR review
    FAILED = "failed"            # extraction errored (see error_message)
    APPROVED = "approved"        # HR approved            (Phase 3)
    REJECTED = "rejected"        # HR rejected            (Phase 3)


class ExtractionSource(str, Enum):
    OCR = "ocr"                      # Tesseract over an image/scan
    PDF_TEXT = "pdf_text"            # embedded PDF text layer, no OCR needed
    RESUME_PARSER = "resume_parser"  # structured resume parsing


class TaskCategory(str, Enum):
    """What kind of onboarding item this is (PRD A.7.5)."""

    TASK = "task"                                  # a general onboarding action
    TRAINING = "training"                          # a training module to complete
    DOCUMENT_CHECKLIST = "document_checklist"      # tied to a document upload
    POLICY_ACKNOWLEDGEMENT = "policy_acknowledgement"  # read-and-accept a policy


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    WAIVED = "waived"          # HR excused it, with a reason


class KnowledgeCategory(str, Enum):
    """What area of the handbook a knowledge document covers (PRD A.7.6)."""

    POLICY = "policy"
    LEAVE = "leave"
    PAYROLL = "payroll"
    BENEFITS = "benefits"
    ONBOARDING = "onboarding"
    IT = "it"
    OTHER = "other"


class KnowledgeStatus(str, Enum):
    """Ingestion lifecycle of a knowledge document."""

    PENDING = "pending"        # stored, not yet chunked/embedded
    INGESTING = "ingesting"    # chunking + embedding in flight
    READY = "ready"            # searchable
    FAILED = "failed"          # ingestion errored (see error_message)


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatOutcome(str, Enum):
    """How a question was resolved — drives the PRD A.10 resolution-rate KPI."""

    ANSWERED = "answered"                # grounded answer above threshold
    ESCALATED_LOW_CONFIDENCE = "escalated_low_confidence"
    ESCALATED_NO_CONTEXT = "escalated_no_context"   # nothing relevant retrieved
    ERROR = "error"


class NotificationType(str, Enum):
    """What happened, from the recipient's point of view (PRD A.7.7).

    The type drives the icon and grouping in the UI, so values are stable and
    name the event rather than the audience — DOCUMENT_APPROVED is one event
    that happens to reach exactly one person.
    """

    # --- Reaches the employee ---------------------------------------------
    DOCUMENT_APPROVED = "document_approved"
    DOCUMENT_REJECTED = "document_rejected"
    TASKS_ASSIGNED = "tasks_assigned"
    TASK_DUE_SOON = "task_due_soon"
    TASK_OVERDUE = "task_overdue"
    ONBOARDING_COMPLETE = "onboarding_complete"

    # --- Reaches HR/Admin --------------------------------------------------
    DOCUMENT_UPLOADED = "document_uploaded"
    INVITATION_ACCEPTED = "invitation_accepted"
    VERIFICATION_FAILED = "verification_failed"
    CHAT_ESCALATED = "chat_escalated"


class VerificationCheckType(str, Enum):
    AADHAAR = "aadhaar"
    PAN = "pan"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class FaceMatchStatus(str, Enum):
    """Mirrors FaceMatchOutcome in app/services/face/base.py."""

    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    NO_FACE_IN_PHOTO = "no_face_in_photo"
    NO_FACE_IN_ID = "no_face_in_id"
    MULTIPLE_FACES_IN_PHOTO = "multiple_faces_in_photo"
    ERROR = "error"


class HolidayType(str, Enum):
    """What kind of day off this is.

    RESTRICTED is the Indian "optional holiday" convention: the company lists
    more of them than any one employee may take. Only the label is modelled —
    the pick-N-of-M entitlement is deliberately not, because nothing in this
    build consumes it.
    """

    PUBLIC = "public"          # national/state holiday, office closed
    RESTRICTED = "restricted"  # optional, employee chooses
    COMPANY = "company"        # company-declared (founding day, shutdown)


class AuditAction(str, Enum):
    """Actions written to the immutable audit log (PRD A.7.9)."""

    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    ACCOUNT_LOCKED = "account_locked"
    TOKEN_REFRESHED = "token_refreshed"
    PASSWORD_RESET_REQUESTED = "password_reset_requested"
    PASSWORD_RESET_COMPLETED = "password_reset_completed"
    PASSWORD_CHANGED = "password_changed"
    EMPLOYEE_CREATED = "employee_created"
    EMPLOYEE_UPDATED = "employee_updated"
    EMPLOYEE_DELETED = "employee_deleted"
    INVITATION_SENT = "invitation_sent"
    INVITATION_RESENT = "invitation_resent"
    INVITATION_REVOKED = "invitation_revoked"
    INVITATION_ACCEPTED = "invitation_accepted"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    PROFILE_UPDATED = "profile_updated"
    # Phase 2 — documents & extraction
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_DELETED = "document_deleted"
    DOCUMENT_DOWNLOADED = "document_downloaded"
    DOCUMENT_EXTRACTED = "document_extracted"
    DOCUMENT_EXTRACTION_FAILED = "document_extraction_failed"
    DOCUMENT_REPROCESSED = "document_reprocessed"
    EXTRACTION_APPLIED = "extraction_applied"
    # Holiday calendar
    HOLIDAY_CREATED = "holiday_created"
    HOLIDAY_UPDATED = "holiday_updated"
    HOLIDAY_DELETED = "holiday_deleted"
    # Phase 3 — verification & HR review
    ID_VERIFICATION_RUN = "id_verification_run"
    FACE_MATCH_RUN = "face_match_run"
    DOCUMENT_APPROVED = "document_approved"
    DOCUMENT_REJECTED = "document_rejected"
    ONBOARDING_STATUS_CHANGED = "onboarding_status_changed"
    # Phase 4 — tasks, training & checklists
    TASK_TEMPLATE_CREATED = "task_template_created"
    TASK_TEMPLATE_UPDATED = "task_template_updated"
    TASK_TEMPLATE_DELETED = "task_template_deleted"
    ASSIGNMENT_RULE_CREATED = "assignment_rule_created"
    ASSIGNMENT_RULE_UPDATED = "assignment_rule_updated"
    ASSIGNMENT_RULE_DELETED = "assignment_rule_deleted"
    TASKS_ASSIGNED = "tasks_assigned"
    TASK_COMPLETED = "task_completed"
    TASK_REOPENED = "task_reopened"
    TASK_WAIVED = "task_waived"
    TASK_ADDED_MANUALLY = "task_added_manually"
    # Phase 5 — knowledge base & chatbot
    KNOWLEDGE_DOC_CREATED = "knowledge_doc_created"
    KNOWLEDGE_DOC_UPDATED = "knowledge_doc_updated"
    KNOWLEDGE_DOC_DELETED = "knowledge_doc_deleted"
    KNOWLEDGE_DOC_INGESTED = "knowledge_doc_ingested"
    KNOWLEDGE_INGEST_FAILED = "knowledge_ingest_failed"
    CHAT_QUESTION_ASKED = "chat_question_asked"
    CHAT_ESCALATED_TO_HR = "chat_escalated_to_hr"
    # Phase 6 — notifications & reminders
    NOTIFICATIONS_MARKED_READ = "notifications_marked_read"
    REMINDERS_RUN = "reminders_run"
    # Phase 7 — reports & session management
    REPORT_EXPORTED = "report_exported"
    SESSION_REVOKED = "session_revoked"
