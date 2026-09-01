"""Seed the database with a bootstrap admin and (optionally) demo data.

    python -m app.seed          # admin only
    python -m app.seed --demo   # admin + HR + a signed-in employee + demo content

Everything here is idempotent and keyed on a natural identifier, so running it
twice adds nothing. --demo is what makes a fresh deployment explorable: without
it there is an admin login and an empty database, which demonstrates nothing.

Demo passwords are printed on creation and are intentionally weak. They are for
a throwaway demo instance; production_problems() refuses to start a production
process that is still using the default admin password.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.employee import Employee
from app.models.enums import HolidayType, OnboardingStatus, UserRole
from app.models.holiday import Holiday
from app.models.user import User

DEMO_HR_EMAIL = "hr@officeiq.dev"
DEMO_HR_PASSWORD = "Hr@123456"

# An employee login, so the employee-facing half of the product can actually be
# demonstrated: onboarding, tasks, the assistant, the holiday calendar and
# requests all look different from this side. Linked to its own Employee row,
# because requests are submitted against an employee record, not a user.
DEMO_EMPLOYEE_EMAIL = "employee@officeiq.dev"
DEMO_EMPLOYEE_PASSWORD = "Employee@12345"

# The HR user gets an employee record too. It is what makes the self-approval
# guard visible: HR submits a request, sees it in their own queue, and cannot
# decide it.
DEMO_HR_EMPLOYEE_CODE = "EMP0102"

DEMO_EMPLOYEES = [
    {
        "employee_code": "EMP0001",
        "first_name": "Ananya",
        "last_name": "Sharma",
        "work_email": "ananya.sharma@officeiq.dev",
        "department": "Engineering",
        "designation": "Software Engineer",
        "date_of_joining": date(2026, 8, 17),
        "onboarding_status": OnboardingStatus.INVITED,
    },
    {
        "employee_code": "EMP0002",
        "first_name": "Rohit",
        "last_name": "Verma",
        "work_email": "rohit.verma@officeiq.dev",
        "department": "Finance",
        "designation": "Financial Analyst",
        "date_of_joining": date(2026, 8, 24),
        "onboarding_status": OnboardingStatus.INVITED,
    },
    {
        "employee_code": "EMP0003",
        "first_name": "Meera",
        "last_name": "Iyer",
        "work_email": "meera.iyer@officeiq.dev",
        "department": "Engineering",
        "designation": "QA Engineer",
        "date_of_joining": date(2026, 9, 1),
        "onboarding_status": OnboardingStatus.REGISTERED,
    },
]


DEMO_HOLIDAYS = [
    ("New Year's Day", date(2026, 1, 1), HolidayType.PUBLIC, None),
    ("Republic Day", date(2026, 1, 26), HolidayType.PUBLIC, None),
    ("Holi", date(2026, 3, 4), HolidayType.PUBLIC, "Festival of colours"),
    ("Eid al-Fitr", date(2026, 3, 20), HolidayType.RESTRICTED, "Date subject to moon sighting"),
    ("Good Friday", date(2026, 4, 3), HolidayType.RESTRICTED, None),
    ("Independence Day", date(2026, 8, 15), HolidayType.PUBLIC, None),
    ("Founders Day", date(2026, 9, 12), HolidayType.COMPANY, "Office closed, all teams"),
    ("Gandhi Jayanti", date(2026, 10, 2), HolidayType.PUBLIC, None),
    ("Diwali", date(2026, 11, 8), HolidayType.PUBLIC, "Festival of lights"),
    ("Christmas Day", date(2026, 12, 25), HolidayType.PUBLIC, None),
]


def _get_or_create_user(db, *, email, password, full_name, role) -> tuple[User, bool]:
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        return existing, False
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        role=role,
    )
    db.add(user)
    db.flush()
    return user, True


def _link_employee_record(
    db,
    *,
    user: User,
    code: str,
    first_name: str,
    last_name: str,
    department: str,
    designation: str,
    created_by_id,
) -> Employee:
    """Give a login an employee record, or adopt the one already there.

    Matched on the user first and the code second, so re-running after a manual
    edit does not create a duplicate for the same person.
    """
    existing = db.scalar(select(Employee).where(Employee.user_id == user.id))
    if existing:
        print(f"  - {existing.employee_code} already linked to {user.email}")
        return existing

    by_code = db.scalar(select(Employee).where(Employee.employee_code == code))
    if by_code:
        by_code.user_id = user.id
        print(f"  ~ linked existing {code} to {user.email}")
        return by_code

    employee = Employee(
        employee_code=code,
        user_id=user.id,
        first_name=first_name,
        last_name=last_name,
        work_email=user.email,
        department=department,
        designation=designation,
        date_of_joining=date(2026, 1, 12),
        onboarding_status=OnboardingStatus.REGISTERED,
        created_by_id=created_by_id,
    )
    db.add(employee)
    db.flush()
    print(f"  + {code} {first_name} {last_name} linked to {user.email}")
    return employee


def seed(with_demo: bool = False) -> None:
    db = SessionLocal()
    try:
        admin, created = _get_or_create_user(
            db,
            email=settings.FIRST_ADMIN_EMAIL.lower(),
            password=settings.FIRST_ADMIN_PASSWORD,
            full_name=settings.FIRST_ADMIN_NAME,
            role=UserRole.ADMIN,
        )
        print(
            f"{'Created' if created else 'Found existing'} admin: {admin.email}"
            + (f" (password: {settings.FIRST_ADMIN_PASSWORD})" if created else "")
        )

        if with_demo:
            hr_user, created = _get_or_create_user(
                db,
                email=DEMO_HR_EMAIL,
                password=DEMO_HR_PASSWORD,
                full_name="Priya Nair",
                role=UserRole.HR,
            )
            print(
                f"{'Created' if created else 'Found existing'} HR user: {hr_user.email}"
                + (f" (password: {DEMO_HR_PASSWORD})" if created else "")
            )

            for row in DEMO_EMPLOYEES:
                if db.scalar(
                    select(Employee.id).where(
                        Employee.employee_code == row["employee_code"]
                    )
                ):
                    print(f"  - {row['employee_code']} already exists, skipping")
                    continue
                db.add(Employee(**row, created_by_id=hr_user.id))
                print(f"  + {row['employee_code']} {row['first_name']} {row['last_name']}")

            # --- A signed-in employee ---------------------------------------
            employee_user, created = _get_or_create_user(
                db,
                email=DEMO_EMPLOYEE_EMAIL,
                password=DEMO_EMPLOYEE_PASSWORD,
                full_name="Arjun Mehta",
                role=UserRole.EMPLOYEE,
            )
            print(
                f"{'Created' if created else 'Found existing'} employee user: "
                f"{employee_user.email}"
                + (f" (password: {DEMO_EMPLOYEE_PASSWORD})" if created else "")
            )
            _link_employee_record(
                db,
                user=employee_user,
                code="EMP0101",
                first_name="Arjun",
                last_name="Mehta",
                department="Engineering",
                designation="Backend Engineer",
                created_by_id=hr_user.id,
            )
            _link_employee_record(
                db,
                user=hr_user,
                code=DEMO_HR_EMPLOYEE_CODE,
                first_name="Priya",
                last_name="Nair",
                department="People",
                designation="HR Manager",
                created_by_id=hr_user.id,
            )

            # --- Holiday calendar -------------------------------------------
            added = 0
            for name, when, kind, note in DEMO_HOLIDAYS:
                exists = db.scalar(
                    select(Holiday.id).where(
                        Holiday.holiday_date == when, Holiday.name == name
                    )
                )
                if exists:
                    continue
                db.add(
                    Holiday(
                        name=name,
                        holiday_date=when,
                        type=kind,
                        description=note,
                        created_by_id=hr_user.id,
                    )
                )
                added += 1
            print(f"  + {added} holiday(s) added ({len(DEMO_HOLIDAYS) - added} already present)")

        db.commit()
        print("Seed complete.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the OfficeIQ database")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Also create HR and employee logins, sample employees and the holiday calendar",
    )
    args = parser.parse_args()
    seed(with_demo=args.demo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
