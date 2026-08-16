"""SQLAlchemy engine, session factory and declarative base."""

import logging
import time
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

connect_args: dict = {}
engine_kwargs: dict = {"pool_pre_ping": True, "future": True}

if settings.DATABASE_URL.startswith("sqlite"):
    # SQLite (used by the test suite) needs a couple of specific knobs, and has
    # no real connection pool to size.
    connect_args["check_same_thread"] = False
else:
    engine_kwargs.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
        pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    )

if settings.DATABASE_URL.startswith("postgresql+psycopg"):
    # Disable psycopg's automatic prepared statements.
    #
    # psycopg3 starts caching a server-side plan after a statement runs a few
    # times. If the table's shape then changes underneath a pooled connection,
    # the next execution fails with "cached plan must not change result type" —
    # which is a real production failure mode during a rolling migration that
    # adds a column while old connections are still checked out, not just a
    # test-suite artefact. It is also outright incompatible with a connection
    # pooler such as PgBouncer in transaction-pooling mode.
    #
    # The cost is re-planning each statement; the benefit is that a deploy
    # cannot half-break the API until every worker restarts.
    connect_args["prepare_threshold"] = None

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, **engine_kwargs)


if settings.SLOW_QUERY_MS > 0:
    # Registered only when enabled — the hooks run on every statement, so an
    # always-on timer would tax the fast path to measure nothing.

    @event.listens_for(engine, "before_cursor_execute")
    def _start_timer(conn, _cursor, _statement, _params, _context, _executemany) -> None:
        conn.info.setdefault("_query_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _log_slow_query(conn, _cursor, statement, params, _context, _executemany) -> None:
        started = conn.info.get("_query_start", [])
        if not started:
            return
        elapsed_ms = (time.perf_counter() - started.pop()) * 1000
        if elapsed_ms >= settings.SLOW_QUERY_MS:
            # Parameters are omitted: they routinely carry personal data, and a
            # log line is the last place it should surface.
            logger.warning(
                "Slow query %.0fms: %s", elapsed_ms, " ".join(statement.split())[:500]
            )

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """SQLite ignores foreign keys unless asked.

    Without this, ON DELETE CASCADE silently does nothing under SQLite while
    working under Postgres — so the test suite would not catch cascade bugs.
    """
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Base(DeclarativeBase):
    """Declarative base shared by every ORM model."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
