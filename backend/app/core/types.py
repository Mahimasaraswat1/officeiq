"""Custom SQLAlchemy column types."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class TZDateTime(TypeDecorator):
    """A timestamp that is always timezone-aware UTC in Python.

    Postgres round-trips `timestamptz` correctly, but SQLite (used by the test
    suite) drops the offset and hands back naive datetimes — which then blow up
    on comparison against `utcnow()`. Normalising in both directions here keeps
    expiry checks dialect-independent.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
