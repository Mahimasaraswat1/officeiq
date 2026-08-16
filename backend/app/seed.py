"""Seed the database with a bootstrap admin and (optionally) demo data.

    python -m app.seed          # admin only
    python -m app.seed --demo   # admin + HR user + sample employees
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
from app.models.enums import OnboardingStatus, UserRole
from app.models.user import User

DEMO_HR_EMAIL = "hr@officeiq.dev"
DEMO_HR_PASSWORD = "Hr@123456"

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
        "--demo", action="store_true", help="Also create an HR user and sample employees"
    )
    args = parser.parse_args()
    seed(with_demo=args.demo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
