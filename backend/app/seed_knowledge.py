"""Seed a starter knowledge base of HR policies and ingest it.

    python -m app.seed_knowledge

These are placeholder policies written to exercise the retrieval pipeline —
replace them with the organisation's real handbook before go-live. Every
document here is editable by HR in the app.
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.enums import KnowledgeCategory
from app.models.knowledge import KnowledgeDocument
from app.services.knowledge import ingest_document

DOCUMENTS: list[dict] = [
    {
        "title": "Annual Leave Policy",
        "category": KnowledgeCategory.LEAVE,
        "source_reference": "Employee Handbook §4.1",
        "version": "2026.1",
        "content": """\
ELIGIBILITY
All full-time employees are eligible for annual leave from their date of joining.
Employees on probation may apply for leave, subject to manager approval.

ANNUAL LEAVE ENTITLEMENT
Full-time employees receive 21 days of paid annual leave per calendar year.
Leave accrues at 1.75 days per completed month of service. Employees who join
part-way through the year receive a pro-rated entitlement for that year.

CARRY FORWARD
A maximum of 10 unused annual leave days may be carried forward into the next
calendar year. Carried-forward days must be used by 31 March, after which they
lapse. Any balance above 10 days is forfeited at year end and is not encashable.

APPLYING FOR LEAVE
Leave requests must be submitted through OfficeIQ at least 7 calendar days in
advance for leave of 3 days or more, and at least 2 working days in advance for
shorter absences. Your reporting manager approves or declines the request.

LEAVE DURING NOTICE PERIOD
Annual leave may not be taken during the notice period without written approval
from both the reporting manager and HR.
""",
    },
    {
        "title": "Sick Leave and Medical Absence",
        "category": KnowledgeCategory.LEAVE,
        "source_reference": "Employee Handbook §4.2",
        "version": "2026.1",
        "content": """\
SICK LEAVE ENTITLEMENT
Employees are entitled to 12 days of paid sick leave per calendar year. Sick
leave does not carry forward and is not encashable.

MEDICAL CERTIFICATE
A medical certificate from a registered practitioner is required for any sick
absence of 3 or more consecutive days. For shorter absences, notifying your
manager by message or email on the first day is sufficient.

EXTENDED MEDICAL LEAVE
Absences beyond the 12-day entitlement are treated as extended medical leave and
require HR approval. Extended medical leave may be unpaid or partially paid
depending on tenure and is assessed case by case.

REPORTING AN ABSENCE
Notify your reporting manager before 10:00 AM on the first day of absence.
Record the absence in OfficeIQ on your return.
""",
    },
    {
        "title": "Payroll and Salary Payment",
        "category": KnowledgeCategory.PAYROLL,
        "source_reference": "Employee Handbook §6.1",
        "version": "2026.1",
        "content": """\
PAYMENT SCHEDULE
Salaries are credited on the last working day of each calendar month. When the
last working day falls on a weekend or public holiday, payment is made on the
preceding working day.

PAYSLIPS
Payslips are issued through OfficeIQ within two working days of salary credit.
Each payslip shows gross salary, statutory deductions, tax withheld, and net pay.

BANK DETAILS
Bank account changes must be submitted to HR at least 10 working days before the
month end to take effect in that month's payroll. Changes submitted later apply
from the following month.

SALARY REVISIONS
Salary reviews take place annually in April. Revised salaries are effective from
1 April and reflected in the April payroll.

PAYROLL QUERIES
Raise payroll discrepancies with HR within 30 days of the payslip date.
""",
    },
    {
        "title": "Code of Conduct",
        "category": KnowledgeCategory.POLICY,
        "source_reference": "Employee Handbook §2",
        "version": "2026.1",
        "content": """\
PROFESSIONAL CONDUCT
Employees are expected to act with integrity, treat colleagues and clients with
respect, and avoid conduct that could damage the company's reputation.

CONFIDENTIALITY
Company information, client data, and employee personal data must not be shared
outside the organisation without written authorisation. Confidentiality
obligations continue after employment ends.

CONFLICT OF INTEREST
Disclose to HR any outside employment, directorship, or financial interest that
could conflict with your duties. Disclosure is required before taking up the
outside interest.

ANTI-HARASSMENT
Harassment, discrimination, and retaliation are prohibited. Complaints may be
raised with HR or through the confidential reporting channel and are
investigated promptly.

DISCIPLINARY ACTION
Breaches may lead to disciplinary action up to and including termination,
following the disciplinary procedure in §2.6.
""",
    },
    {
        "title": "Working Hours and Remote Work",
        "category": KnowledgeCategory.POLICY,
        "source_reference": "Employee Handbook §3",
        "version": "2026.1",
        "content": """\
STANDARD WORKING HOURS
Standard hours are 9:30 AM to 6:30 PM, Monday to Friday, with a one-hour lunch
break. Core hours during which all employees should be available are 11:00 AM to
4:00 PM.

FLEXIBLE START
Employees may start between 8:30 AM and 10:30 AM with manager agreement,
provided core hours are covered and the daily total is met.

REMOTE WORK
Employees may work remotely up to 2 days per week with manager approval. Fully
remote arrangements require HR approval and are reviewed every 6 months.

OVERTIME
Overtime is not automatically compensated for salaried roles. Sustained
additional hours should be raised with your manager and may be offset with time
in lieu.
""",
    },
    {
        "title": "Employee Benefits",
        "category": KnowledgeCategory.BENEFITS,
        "source_reference": "Employee Handbook §5",
        "version": "2026.1",
        "content": """\
HEALTH INSURANCE
All confirmed employees are enrolled in the group health insurance scheme from
their date of confirmation. Coverage includes the employee, spouse, and up to two
dependent children. The company pays the base premium; additional dependants may
be added at the employee's cost.

PROVIDENT FUND
Statutory provident fund contributions are deducted monthly and matched by the
company at the statutory rate.

LEARNING ALLOWANCE
Each employee has an annual learning allowance of 30,000 for courses,
certifications, conferences, and books. Claims require manager approval and a
receipt, and must be submitted within the same financial year.

WELLNESS
The company reimburses gym or fitness memberships up to 12,000 per year on
production of receipts.
""",
    },
    {
        "title": "Onboarding and Probation",
        "category": KnowledgeCategory.ONBOARDING,
        "source_reference": "Employee Handbook §1",
        "version": "2026.1",
        "content": """\
ONBOARDING DOCUMENTS
New joiners must submit Aadhaar, PAN, a passport-size photograph, and
educational certificates through OfficeIQ within 7 days of joining. HR verifies
each document before onboarding is marked complete.

PROBATION PERIOD
The standard probation period is 6 months from the date of joining. Probation may
be extended once by up to 3 months where performance objectives have not been
met, with written notice.

CONFIRMATION
Confirmation follows a review with your reporting manager at the end of
probation. Health insurance enrolment and the learning allowance take effect on
confirmation.

NOTICE PERIOD
During probation, the notice period is 15 days for either party. After
confirmation, the notice period is 60 days.
""",
    },
    {
        "title": "IT Equipment and Access",
        "category": KnowledgeCategory.IT,
        "source_reference": "IT Policy §1",
        "version": "2026.1",
        "content": """\
EQUIPMENT ISSUE
Laptops and accessories are issued on the first working day. Equipment remains
company property and must be returned on the last working day.

ACCOUNT ACCESS
Email and system accounts are provisioned before the joining date. Raise access
requests for additional systems through the IT helpdesk with manager approval.

ACCEPTABLE USE
Company devices are for business use. Do not install unlicensed software, and do
not store company data on personal cloud accounts.

PASSWORDS AND SECURITY
Use the company password manager. Multi-factor authentication is mandatory on
email and all systems holding employee or client data. Report a lost or stolen
device to IT immediately.

DAMAGE OR LOSS
Report damaged equipment to the IT helpdesk. Repair or replacement is at company
cost unless the damage results from negligence.
""",
    },
]


def seed_knowledge() -> None:
    db = SessionLocal()
    created_ids = []
    try:
        for spec in DOCUMENTS:
            existing = db.scalar(
                select(KnowledgeDocument).where(KnowledgeDocument.title == spec["title"])
            )
            if existing:
                print(f"  - {spec['title']!r} already exists, skipping")
                continue
            document = KnowledgeDocument(**spec)
            db.add(document)
            db.flush()
            created_ids.append(document.id)
            print(f"  + {spec['title']}")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    if not created_ids:
        print("Nothing new to ingest.")
        return

    print(f"\nIngesting {len(created_ids)} document(s)…")
    for document_id in created_ids:
        ingest_document(document_id)

    db = SessionLocal()
    try:
        total = 0
        for document_id in created_ids:
            document = db.get(KnowledgeDocument, document_id)
            if document is None:
                continue
            total += document.chunk_count
            marker = "ok " if document.status.value == "ready" else "FAIL"
            print(
                f"  [{marker}] {document.title}: {document.chunk_count} chunk(s)"
                + (f" — {document.error_message}" if document.error_message else "")
            )
        print(f"\nKnowledge base seeded: {total} chunk(s) embedded and searchable.")
    finally:
        db.close()


if __name__ == "__main__":
    seed_knowledge()
    sys.exit(0)
