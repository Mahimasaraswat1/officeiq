"""Do the migrations actually produce the schema the models describe?

The rest of the suite builds its schema with Base.metadata.create_all(), which
is fast but means it never executes a single migration. Anything that only a
migration can get wrong — a missing ALTER TYPE, a column added to the model but
not to a revision — passes every other test and then fails on the first real
request against a migrated database.

These tests run the migrations for real, so that gap is covered. They need
Postgres (SQLite does not enforce enum membership, which is the failure mode
being guarded) and are skipped otherwise.
"""

from __future__ import annotations

import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.models.enums import NotificationType

TEST_URL = os.getenv("TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not TEST_URL.startswith("postgresql"),
    reason="migration checks need Postgres; set TEST_DATABASE_URL",
)


@pytest.fixture(scope="module")
def migrated_url() -> str:
    """A throwaway database with `alembic upgrade head` actually applied.

    Built separately from the suite's own database so running the migrations
    cannot disturb the create_all() schema the other tests rely on.
    """
    admin_url = TEST_URL.rsplit("/", 1)[0] + "/postgres"
    name = f"officeiq_mig_{uuid.uuid4().hex[:8]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    url = TEST_URL.rsplit("/", 1)[0] + f"/{name}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)

    # alembic/env.py sets the URL from settings.DATABASE_URL, overriding
    # whatever is passed in the config — so the setting itself has to be
    # redirected, or this would migrate the developer's own database.
    from app.core.config import settings

    original = settings.DATABASE_URL
    settings.DATABASE_URL = url
    try:
        command.upgrade(config, "head")
        yield url
    finally:
        settings.DATABASE_URL = original
        admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :n AND pid <> pg_backend_pid()"
                ),
                {"n": name},
            )
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


def _enum_values(url: str, type_name: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return set(
                connection.execute(
                    text(
                        "SELECT e.enumlabel FROM pg_enum e "
                        "JOIN pg_type t ON t.oid = e.enumtypid "
                        "WHERE t.typname = :n"
                    ),
                    {"n": type_name},
                ).scalars()
            )
    finally:
        engine.dispose()


def test_migrations_create_every_notification_type(migrated_url):
    """A NotificationType the migrated enum lacks is a guaranteed 500 in prod.

    Alembic's autogenerate does not detect values added to an existing enum, so
    adding one to NotificationType also means writing an ALTER TYPE by hand.
    This is the test that says so.
    """
    in_db = _enum_values(migrated_url, "notification_type")
    missing = sorted({t.value for t in NotificationType} - in_db)
    assert not missing, (
        f"NotificationType values missing after `alembic upgrade head`: {missing}. "
        "Add `ALTER TYPE notification_type ADD VALUE ...` to a migration."
    )


def test_migrations_create_the_request_and_holiday_tables(migrated_url):
    """The two module tables exist after a migration-only build."""
    engine = create_engine(migrated_url)
    try:
        with engine.connect() as connection:
            present = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                ).scalars()
            )
    finally:
        engine.dispose()
    assert {"holidays", "requests"} <= present
