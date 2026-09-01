"""The demo seed: it must be safe to run twice, and it must produce a login.

A fresh deployment runs this to become explorable. Two things make it useless
if they break silently: creating duplicates on a re-run (a deploy that runs it
on every boot), and producing no employee login (leaving half the product
undemonstrable, which is how it was before).
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.employee import Employee
from app.models.enums import HolidayType, UserRole
from app.models.holiday import Holiday
from app.models.user import User
from app.seed import DEMO_HOLIDAYS, seed


def _counts(db) -> tuple[int, int, int]:
    return (
        db.scalar(select(func.count()).select_from(User)),
        db.scalar(select(func.count()).select_from(Employee)),
        db.scalar(select(func.count()).select_from(Holiday)),
    )


def test_seeding_twice_changes_nothing(db):
    """A deploy that seeds on every boot must not accumulate duplicates."""
    seed(with_demo=True)
    first = _counts(db)

    seed(with_demo=True)
    assert _counts(db) == first


def test_the_demo_seed_creates_a_login_for_every_role(db):
    """All three roles must be reachable, or half the product cannot be shown."""
    seed(with_demo=True)
    roles = set(db.scalars(select(User.role)))
    assert {UserRole.ADMIN, UserRole.HR, UserRole.EMPLOYEE} <= roles


def test_the_employee_login_is_linked_to_an_employee_record(db):
    """Requests are submitted against an employee record, not a user."""
    seed(with_demo=True)
    user = db.scalar(select(User).where(User.role == UserRole.EMPLOYEE))
    employee = db.scalar(select(Employee).where(Employee.user_id == user.id))
    assert employee is not None
    assert employee.work_email == user.email


def test_hr_is_linked_too_so_the_self_approval_guard_is_demonstrable(db):
    """HR needs an employee record to submit a request against itself."""
    seed(with_demo=True)
    hr = db.scalar(select(User).where(User.role == UserRole.HR))
    assert db.scalar(select(Employee).where(Employee.user_id == hr.id)) is not None


def test_the_holiday_calendar_is_seeded_with_a_usable_spread(db):
    seed(with_demo=True)
    rows = list(db.scalars(select(Holiday)))
    assert len(rows) == len(DEMO_HOLIDAYS)
    # A calendar of one type would not exercise the page's own grouping.
    assert {r.type for r in rows} == {
        HolidayType.PUBLIC,
        HolidayType.RESTRICTED,
        HolidayType.COMPANY,
    }


def test_seeding_without_demo_creates_only_the_admin(db):
    """The default path is for a real deployment: a way in, and nothing else."""
    seed(with_demo=False)
    users = list(db.scalars(select(User)))
    assert [u.role for u in users] == [UserRole.ADMIN]
    assert db.scalar(select(func.count()).select_from(Employee)) == 0
    assert db.scalar(select(func.count()).select_from(Holiday)) == 0
