"""Seed a starter catalogue of task templates and assignment rules.

    python -m app.seed_tasks

These are only defaults to get an organisation going — everything here is
editable by HR through the UI without a deploy, which is the point of keeping
rules in the database.
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.enums import DocumentType, TaskCategory
from app.models.task import AssignmentRule, AssignmentRuleItem, TaskTemplate

# code, title, category, due_days, mandatory, document_type, url, minutes
TEMPLATES: list[dict] = [
    # --- Document checklist (closes itself when the document is approved) ---
    dict(code="DOC_AADHAAR", title="Submit Aadhaar card",
         category=TaskCategory.DOCUMENT_CHECKLIST, default_due_days=3,
         required_document_type=DocumentType.AADHAAR,
         description="Upload a clear scan or photo of your Aadhaar card."),
    dict(code="DOC_PAN", title="Submit PAN card",
         category=TaskCategory.DOCUMENT_CHECKLIST, default_due_days=3,
         required_document_type=DocumentType.PAN,
         description="Upload a clear scan or photo of your PAN card."),
    dict(code="DOC_PHOTO", title="Submit passport photo",
         category=TaskCategory.DOCUMENT_CHECKLIST, default_due_days=3,
         required_document_type=DocumentType.PHOTO,
         description="Upload a recent front-facing passport-style photo."),
    dict(code="DOC_CERTIFICATES", title="Submit educational certificates",
         category=TaskCategory.DOCUMENT_CHECKLIST, default_due_days=7,
         required_document_type=DocumentType.CERTIFICATE, is_mandatory=False,
         description="Upload your highest-qualification certificate."),

    # --- Policy acknowledgements ---
    dict(code="POLICY_CODE_OF_CONDUCT", title="Read and accept the Code of Conduct",
         category=TaskCategory.POLICY_ACKNOWLEDGEMENT, default_due_days=5,
         estimated_minutes=20),
    dict(code="POLICY_LEAVE", title="Read the Leave Policy",
         category=TaskCategory.POLICY_ACKNOWLEDGEMENT, default_due_days=7,
         estimated_minutes=15),
    dict(code="POLICY_INFOSEC", title="Read and accept the Information Security Policy",
         category=TaskCategory.POLICY_ACKNOWLEDGEMENT, default_due_days=5,
         estimated_minutes=25),

    # --- General onboarding tasks ---
    dict(code="IT_ACCOUNTS", title="Collect IT accounts and laptop",
         category=TaskCategory.TASK, default_due_days=1,
         description="Pick up your laptop and access credentials from the IT desk."),
    dict(code="HR_BANK_DETAILS", title="Submit bank details for payroll",
         category=TaskCategory.TASK, default_due_days=5,
         description="Share your bank account details with HR for salary processing."),
    dict(code="HR_EMERGENCY_CONTACT", title="Provide emergency contact details",
         category=TaskCategory.TASK, default_due_days=5),
    dict(code="MEET_MANAGER", title="Introductory meeting with your manager",
         category=TaskCategory.TASK, default_due_days=2),
    dict(code="TEAM_INTRO", title="Team introduction session",
         category=TaskCategory.TASK, default_due_days=3, is_mandatory=False),

    # --- Training ---
    dict(code="TRAIN_ORIENTATION", title="Company orientation",
         category=TaskCategory.TRAINING, default_due_days=7, estimated_minutes=90),
    dict(code="TRAIN_POSH", title="POSH (workplace harassment prevention) training",
         category=TaskCategory.TRAINING, default_due_days=14, estimated_minutes=60),
    dict(code="TRAIN_DATA_PRIVACY", title="Data privacy and handling training",
         category=TaskCategory.TRAINING, default_due_days=14, estimated_minutes=45),
    dict(code="TRAIN_SECURE_CODING", title="Secure coding practices",
         category=TaskCategory.TRAINING, default_due_days=21, estimated_minutes=120),
    dict(code="TRAIN_FINANCE_COMPLIANCE", title="Financial compliance and controls",
         category=TaskCategory.TRAINING, default_due_days=21, estimated_minutes=90),
]

# name, department, designation, description, template codes
RULES: list[dict] = [
    dict(
        name="All new joiners",
        department=None,
        designation=None,
        priority=10,
        description="Baseline onboarding applied to everyone, regardless of team.",
        codes=[
            "DOC_AADHAAR", "DOC_PAN", "DOC_PHOTO", "DOC_CERTIFICATES",
            "POLICY_CODE_OF_CONDUCT", "POLICY_LEAVE", "POLICY_INFOSEC",
            "IT_ACCOUNTS", "HR_BANK_DETAILS", "HR_EMERGENCY_CONTACT",
            "MEET_MANAGER", "TEAM_INTRO",
            "TRAIN_ORIENTATION", "TRAIN_POSH", "TRAIN_DATA_PRIVACY",
        ],
    ),
    dict(
        name="Engineering",
        department="Engineering",
        designation=None,
        priority=20,
        description="Additional training for engineering hires.",
        codes=["TRAIN_SECURE_CODING"],
    ),
    dict(
        name="Finance",
        department="Finance",
        designation=None,
        priority=20,
        description="Additional compliance training for finance hires.",
        codes=["TRAIN_FINANCE_COMPLIANCE"],
    ),
]


def seed_tasks() -> None:
    db = SessionLocal()
    try:
        templates: dict[str, TaskTemplate] = {}
        created = 0
        for spec in TEMPLATES:
            existing = db.scalar(
                select(TaskTemplate).where(TaskTemplate.code == spec["code"])
            )
            if existing:
                templates[spec["code"]] = existing
                continue
            template = TaskTemplate(**spec)
            db.add(template)
            db.flush()
            templates[spec["code"]] = template
            created += 1
        print(f"Task templates: {created} created, {len(TEMPLATES) - created} already present")

        rules_created = 0
        for spec in RULES:
            if db.scalar(select(AssignmentRule).where(AssignmentRule.name == spec["name"])):
                print(f"  - rule {spec['name']!r} already exists, skipping")
                continue

            rule = AssignmentRule(
                name=spec["name"],
                description=spec["description"],
                department=spec["department"],
                designation=spec["designation"],
                priority=spec["priority"],
            )
            db.add(rule)
            db.flush()

            for code in spec["codes"]:
                template = templates.get(code)
                if template is None:
                    print(f"    ! unknown template code {code}, skipping")
                    continue
                db.add(
                    AssignmentRuleItem(rule_id=rule.id, template_id=template.id)
                )
            rules_created += 1
            print(f"  + rule {spec['name']!r} with {len(spec['codes'])} item(s)")

        db.commit()
        print(f"Assignment rules: {rules_created} created.")
        print("Seed complete — HR can edit all of this in the app without a deploy.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_tasks()
    sys.exit(0)
