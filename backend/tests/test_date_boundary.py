"""One definition of "today", pinned at the boundary where it used to break.

EmployeeTask.is_overdue() used the server's local date while the dashboard used
UTC. East of UTC the two disagree for part of every day — 05:30 nightly at
+05:30 — so a task could be overdue on one screen and not on another, and four
tests failed only between midnight and dawn. Both the behaviour and the "only
one definition exists" rule are pinned here, because the failure is invisible
for nineteen hours a day.
"""

from __future__ import annotations

import pathlib
import re
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core import security
from app.models.enums import TaskStatus
from app.models.task import EmployeeTask


# --- The helper itself -------------------------------------------------------


def test_today_utc_follows_utc_not_the_servers_local_zone(monkeypatch):
    """At 20:30 UTC it is already tomorrow in IST; today_utc() must say UTC."""
    fixed = datetime(2026, 9, 1, 20, 30, tzinfo=timezone.utc)  # 02:00 IST on Sep 2
    monkeypatch.setattr(security, "utcnow", lambda: fixed)
    assert security.today_utc() == date(2026, 9, 1)


# --- is_overdue at the boundary ---------------------------------------------


@pytest.fixture
def task_due(request):
    def _make(due: date) -> EmployeeTask:
        return EmployeeTask(
            title="Sign the handbook",
            status=TaskStatus.PENDING,
            due_date=due,
        )

    return _make


def test_a_task_due_today_is_not_overdue(task_due):
    """The classic off-by-one: due today means due, not late."""
    today = security.today_utc()
    assert task_due(today).is_overdue() is False


def test_a_task_due_yesterday_is_overdue(task_due):
    today = security.today_utc()
    assert task_due(today - timedelta(days=1)).is_overdue() is True


def test_overdue_uses_utc_during_the_ist_night(monkeypatch, task_due):
    """The exact window the bug lived in.

    At 02:00 IST on 2 Sep it is still 1 Sep in UTC. A task due 1 Sep is not yet
    overdue; under the old local-date logic it would have been.
    """
    import app.models.task as task_module

    fixed_utc_date = date(2026, 9, 1)  # while local IST already reads 2 Sep
    monkeypatch.setattr(task_module, "today_utc", lambda: fixed_utc_date)

    assert task_due(date(2026, 9, 1)).is_overdue() is False
    assert task_due(date(2026, 8, 31)).is_overdue() is True


def test_a_closed_task_is_never_overdue(task_due):
    task = task_due(security.today_utc() - timedelta(days=30))
    task.status = TaskStatus.COMPLETED
    assert task.is_overdue() is False


def test_an_explicit_today_still_wins(task_due):
    """Callers that pass a date must not be overridden by the default."""
    task = task_due(date(2026, 9, 1))
    assert task.is_overdue(today=date(2026, 9, 5)) is True
    assert task.is_overdue(today=date(2026, 8, 20)) is False


# --- The rule, not just the behaviour ---------------------------------------


BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_ROOT = BACKEND_ROOT / "app"
TESTS_ROOT = BACKEND_ROOT / "tests"

# security.py defines the helper and explains the history in its docstring;
# this file names the old call in prose for the same reason.
_ALLOWED = {APP_ROOT / "core" / "security.py", pathlib.Path(__file__).resolve()}

_LOCAL_DATE_CALL = re.compile(r"\bdate\.today\(\)|\bdatetime\.now\(\s*\)")


@pytest.mark.parametrize("root", [APP_ROOT, TESTS_ROOT], ids=["app", "tests"])
def test_nothing_reads_the_local_calendar_date(root):
    """A new date.today() would silently reintroduce the split.

    This is the test that actually stops the regression: the behavioural checks
    above only fail during the few hours a day when the zones disagree, so on
    most CI runs they would pass with the bug present.

    Tests are covered as well as app code. The fixtures were half the original
    problem — they built due dates from the local calendar and asserted against
    UTC endpoints, which is why four tests failed only between midnight and
    dawn.
    """
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if path.resolve() in _ALLOWED:
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            code = line.split("#", 1)[0]
            if _LOCAL_DATE_CALL.search(code):
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{number}: {line.strip()}")

    assert not offenders, (
        "These read the server's local date instead of app.core.security.today_utc():\n  "
        + "\n  ".join(offenders)
    )
