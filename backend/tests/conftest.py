"""Test fixtures.

Defaults to a throwaway SQLite file so CI needs no services. Set
TEST_DATABASE_URL to run the same suite against a real Postgres instance, e.g.

    TEST_DATABASE_URL=postgresql+psycopg://officeiq:officeiq@localhost:5433/officeiq_test pytest
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Generator
from pathlib import Path

# Configure the environment before any app module reads settings.
_TMP = Path(tempfile.mkdtemp(prefix="officeiq-tests-"))
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}"
)
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["EMAIL_BACKEND"] = "file"
os.environ["EMAIL_OUTBOX_DIR"] = str(_TMP / "outbox")
os.environ["ENVIRONMENT"] = "local"
os.environ["DEBUG"] = "false"  # keep test output readable

# Phase 2: filesystem storage and inline extraction keep tests deterministic.
os.environ["STORAGE_BACKEND"] = "local"
os.environ["STORAGE_LOCAL_ROOT"] = str(_TMP / "storage")
os.environ["OCR_PROCESS_SYNCHRONOUSLY"] = "true"
# Real Tesseract is exercised by tests/test_ocr_real.py, which skips when the
# binary is missing. Everything else uses the stub so results are stable.
os.environ.setdefault("OCR_ENGINE", "stub")
os.environ["VERIFICATION_PROCESS_SYNCHRONOUSLY"] = "true"
# Real face matching is exercised by tests/test_face_match_real.py, which
# skips when the ONNX models are absent.
os.environ.setdefault("FACE_MATCHER", "stub")

# Phase 5: deterministic embeddings + a stub generator, so the RAG pipeline
# is testable without a Voyage or Anthropic API key. Real Claude generation
# is exercised by tests/test_chat_real.py, which skips without a key.
os.environ.setdefault("EMBEDDING_PROVIDER", "local")
os.environ.setdefault("CHAT_PROVIDER", "stub")
os.environ["INGEST_PROCESS_SYNCHRONOUSLY"] = "true"

# Phase 8: the limiter stays *on* so its code path is exercised by every test,
# but with limits high enough that ordinary tests never trip it. The dedicated
# tests in test_hardening.py lower them deliberately. Counters are also reset
# between tests (see the fixture below), so one test cannot throttle the next.
os.environ.setdefault("RATE_LIMIT_ENABLED", "true")
os.environ.setdefault("RATE_LIMIT_LOGIN", "1000/minute")
os.environ.setdefault("RATE_LIMIT_PASSWORD_RESET", "1000/minute")
os.environ.setdefault("RATE_LIMIT_CHAT", "1000/minute")
os.environ.setdefault("RATE_LIMIT_REPORTS", "1000/minute")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text as sa_text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.user import User  # noqa: E402

API = "/api/v1"

ADMIN = {"email": "admin@example.com", "password": "Admin@12345"}
HR = {"email": "hr@example.com", "password": "HrPass@123"}


@pytest.fixture(autouse=True)
def _fresh_database() -> Generator[None, None, None]:
    """Rebuild the schema and clear stored files before every test."""
    # create_all() does not run migrations, so the pgvector extension that
    # migration 0005 installs has to be created here too — otherwise the
    # vector(1024) column fails with 'type "vector" does not exist'.
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.execute(sa_text("CREATE EXTENSION IF NOT EXISTS vector"))

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # Rebuilding the schema invalidates whatever a pooled connection cached
    # about it. Dropping the pool guarantees the next test gets connections
    # that never saw the previous test's tables — without this, Postgres
    # eventually fails with "cached plan must not change result type".
    engine.dispose()

    from app.core.ratelimit import get_backend
    from app.services.storage import LocalStorageBackend, get_storage

    get_backend().reset()

    storage = get_storage()
    if isinstance(storage, LocalStorageBackend):
        storage.purge_all()

    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def _make_user(db: Session, *, email: str, password: str, role: UserRole) -> User:
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=f"Test {role.value}",
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def admin_user(db: Session) -> User:
    return _make_user(db, email=ADMIN["email"], password=ADMIN["password"], role=UserRole.ADMIN)


@pytest.fixture
def hr_user(db: Session) -> User:
    return _make_user(db, email=HR["email"], password=HR["password"], role=UserRole.HR)


def login(client: TestClient, email: str, password: str) -> dict:
    response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(client: TestClient, email: str, password: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {login(client, email, password)['access_token']}"}


@pytest.fixture
def admin_headers(client: TestClient, admin_user: User) -> dict[str, str]:
    return auth_headers(client, ADMIN["email"], ADMIN["password"])


@pytest.fixture
def hr_headers(client: TestClient, hr_user: User) -> dict[str, str]:
    return auth_headers(client, HR["email"], HR["password"])
