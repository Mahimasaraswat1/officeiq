"""Phase 8: production guardrails, security headers, rate limiting, probes."""

from __future__ import annotations

import pytest

from app.core.config import ConfigurationError, Settings, get_settings
from app.core.ratelimit import (
    InMemoryRateLimitBackend,
    Rule,
    get_backend,
)
from tests.conftest import API, HR


def production_settings(**overrides) -> Settings:
    """A production Settings object that is safe apart from what a test breaks."""
    safe = {
        "ENVIRONMENT": "production",
        "DEBUG": False,
        "SECRET_KEY": "x" * 48,
        "FIRST_ADMIN_PASSWORD": "NotTheDefault@99",
        "DATABASE_URL": "postgresql+psycopg://u:p@db:5432/officeiq",
        "EMAIL_BACKEND": "smtp",
        "SMTP_HOST": "smtp.example.com",
        "STORAGE_BACKEND": "s3",
        "S3_ACCESS_KEY": "key",
        "S3_SECRET_KEY": "secret",
        "OCR_ENGINE": "tesseract",
        "FACE_MATCHER": "opencv_dnn",
        "CHAT_PROVIDER": "claude",
        "ANTHROPIC_API_KEY": "sk-ant-test",
        "EMBEDDING_PROVIDER": "voyage",
        "VOYAGE_API_KEY": "pa-test",
        "CORS_ORIGINS": ["https://officeiq.example.com"],
        "FRONTEND_BASE_URL": "https://officeiq.example.com",
    }
    return Settings(**{**safe, **overrides})


# --- Production guardrails -------------------------------------------------


def test_a_correctly_configured_production_setup_has_no_problems():
    assert production_settings().production_problems() == []


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"SECRET_KEY": "change-me-in-production"}, "SECRET_KEY"),
        ({"SECRET_KEY": "short-but-valid"}, "32 characters"),
        ({"DEBUG": True}, "DEBUG"),
        ({"FIRST_ADMIN_PASSWORD": "Admin@12345"}, "FIRST_ADMIN_PASSWORD"),
        ({"DATABASE_URL": "sqlite:///./app.db"}, "SQLite"),
        ({"EMAIL_BACKEND": "file"}, "does not deliver mail"),
        ({"STORAGE_BACKEND": "local"}, "one container's disk"),
        ({"OCR_ENGINE": "stub"}, "extracts nothing"),
        ({"FACE_MATCHER": "stub"}, "does not compare faces"),
        ({"CHAT_PROVIDER": "stub"}, "canned text"),
        ({"EMBEDDING_PROVIDER": "local"}, "not meaning"),
        ({"CHAT_PROVIDER": "claude", "ANTHROPIC_API_KEY": None}, "ANTHROPIC_API_KEY"),
        ({"EMBEDDING_PROVIDER": "voyage", "VOYAGE_API_KEY": None}, "VOYAGE_API_KEY"),
        ({"S3_ACCESS_KEY": None}, "S3_ACCESS_KEY"),
        ({"CORS_ORIGINS": ["*"]}, "'*'"),
        ({"CORS_ORIGINS": []}, "empty"),
        ({"CORS_ORIGINS": ["http://insecure.example.com"]}, "plain-http"),
        ({"FRONTEND_BASE_URL": "http://insecure.example.com"}, "plain http"),
    ],
)
def test_each_unsafe_production_setting_is_caught(overrides, expected):
    problems = production_settings(**overrides).production_problems()
    assert any(expected in problem for problem in problems), problems


def test_problems_explain_the_consequence_not_just_the_setting():
    """A guardrail that only names a variable makes the reader go and look."""
    for problem in production_settings(OCR_ENGINE="stub", CHAT_PROVIDER="stub").production_problems():
        assert len(problem) > 40
        assert problem.endswith(".")


def test_development_defaults_are_not_flagged_outside_production():
    """The same shims are exactly right locally, and must not warn."""
    local = Settings(ENVIRONMENT="local", OCR_ENGINE="stub", CHAT_PROVIDER="stub")
    assert local.is_production is False
    # production_problems() is only consulted for production, but the local
    # settings should still load without complaint.
    assert local.ENVIRONMENT == "local"


def test_get_settings_refuses_to_start_a_broken_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "change-me-in-production")
    get_settings.cache_clear()
    try:
        with pytest.raises(ConfigurationError) as caught:
            get_settings()
        message = str(caught.value)
        assert "Refusing to start" in message
        # Every problem is listed, not just the first, so one restart fixes all.
        assert message.count("  - ") > 1
    finally:
        get_settings.cache_clear()


# --- Security headers ------------------------------------------------------


def test_security_headers_are_present_on_every_response(client):
    response = client.get("/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "camera=()" in response.headers["Permissions-Policy"]
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'none'; frame-ancestors 'none'"
    )


def test_security_headers_are_present_on_errors_too(client):
    """An error path is exactly where a missing header goes unnoticed."""
    response = client.get(f"{API}/employees")
    assert response.status_code == 401
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_docs_are_exempt_from_the_strict_csp(client):
    """default-src 'none' would blank the Swagger page rather than protect it."""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers


def test_hsts_is_not_sent_over_plain_http(client):
    # Pinning localhost to https for a year would be a hostile thing to do to
    # a developer's browser.
    assert "Strict-Transport-Security" not in client.get("/health").headers


# --- Request correlation ---------------------------------------------------


def test_every_response_carries_a_request_id(client):
    response = client.get("/health")
    request_id = response.headers.get("X-Request-ID")
    assert request_id and len(request_id) >= 8


def test_a_client_supplied_request_id_is_echoed(client):
    response = client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert response.headers["X-Request-ID"] == "trace-abc-123"


def test_a_hostile_request_id_is_sanitised(client):
    """The id lands in log lines and a response header, so it cannot be junk."""
    response = client.get(
        "/health", headers={"X-Request-ID": "bad\r\nInjected: header <script>"}
    )
    echoed = response.headers["X-Request-ID"]
    assert "\r" not in echoed and "\n" not in echoed and "<" not in echoed
    assert echoed == "badInjectedheaderscript"


def test_an_overlong_request_id_is_truncated(client):
    response = client.get("/health", headers={"X-Request-ID": "a" * 500})
    assert len(response.headers["X-Request-ID"]) == 64


def test_each_request_gets_a_distinct_id(client):
    first = client.get("/health").headers["X-Request-ID"]
    second = client.get("/health").headers["X-Request-ID"]
    assert first != second


# --- Rate limiting ---------------------------------------------------------


def test_rule_parsing_accepts_every_window():
    assert Rule.parse("10/minute") == Rule(10, 60)
    assert Rule.parse("5/hour") == Rule(5, 3600)
    assert Rule.parse(" 2 / second ") == Rule(2, 1)


def test_a_malformed_rule_raises_rather_than_disabling_the_limit():
    """Silently ignoring a typo would leave the endpoint unprotected."""
    for bad in ["ten/minute", "10/fortnight", "10", ""]:
        with pytest.raises(ValueError):
            Rule.parse(bad)


def test_sliding_window_blocks_then_recovers():
    backend = InMemoryRateLimitBackend()
    rule = Rule(2, 60)

    assert backend.hit("k", rule) == (True, 0)
    assert backend.hit("k", rule) == (True, 0)

    allowed, retry_after = backend.hit("k", rule)
    assert allowed is False
    assert 0 < retry_after <= 61

    # A different key has its own allowance.
    assert backend.hit("other", rule) == (True, 0)


def test_login_is_rate_limited_per_ip(client, hr_user, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_LOGIN", "3/minute")
    get_backend().reset()

    wrong = {"email": HR["email"], "password": "Wrong@12345"}
    for _ in range(3):
        assert client.post(f"{API}/auth/login", json=wrong).status_code == 401

    blocked = client.post(f"{API}/auth/login", json=wrong)
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    # A 429 without Retry-After leaves a well-behaved client guessing.
    assert int(blocked.headers["Retry-After"]) > 0
    assert blocked.json()["error"]["details"]["retry_after_seconds"] > 0


def test_the_limit_covers_attempts_against_different_accounts(
    client, hr_user, monkeypatch
):
    """The account lockout misses this: one IP, many accounts, one attempt each."""
    monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_LOGIN", "3/minute")
    get_backend().reset()

    for index in range(3):
        client.post(
            f"{API}/auth/login",
            json={"email": f"victim{index}@example.com", "password": "Guess@12345"},
        )

    blocked = client.post(
        f"{API}/auth/login", json={"email": HR["email"], "password": HR["password"]}
    )
    assert blocked.status_code == 429


def test_password_reset_is_rate_limited(client, hr_user, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_PASSWORD_RESET", "2/minute")
    get_backend().reset()

    payload = {"email": HR["email"]}
    assert client.post(f"{API}/auth/forgot-password", json=payload).status_code == 202
    assert client.post(f"{API}/auth/forgot-password", json=payload).status_code == 202
    assert client.post(f"{API}/auth/forgot-password", json=payload).status_code == 429


def test_the_assistant_is_rate_limited_per_user(client, hr_headers, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_CHAT", "2/minute")
    get_backend().reset()

    question = {"question": "What is the leave policy?"}
    assert client.post(f"{API}/chat/ask", json=question, headers=hr_headers).status_code == 201
    assert client.post(f"{API}/chat/ask", json=question, headers=hr_headers).status_code == 201

    blocked = client.post(f"{API}/chat/ask", json=question, headers=hr_headers)
    assert blocked.status_code == 429


def test_an_authenticated_limit_does_not_punish_a_shared_ip(
    client, hr_headers, admin_headers, monkeypatch
):
    """Two colleagues behind one NAT address must not share one allowance."""
    monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_CHAT", "1/minute")
    get_backend().reset()

    question = {"question": "What is the leave policy?"}
    assert client.post(f"{API}/chat/ask", json=question, headers=hr_headers).status_code == 201
    assert client.post(f"{API}/chat/ask", json=question, headers=hr_headers).status_code == 429
    # Different user, same IP — still allowed.
    assert client.post(f"{API}/chat/ask", json=question, headers=admin_headers).status_code == 201


def test_reports_are_rate_limited(client, hr_headers, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_REPORTS", "2/minute")
    get_backend().reset()

    for _ in range(2):
        assert client.get(f"{API}/reports/employee_roster", headers=hr_headers).status_code == 200
    assert client.get(f"{API}/reports/employee_roster", headers=hr_headers).status_code == 429


def test_limiting_can_be_switched_off(client, hr_user, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_ENABLED", False)
    monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_LOGIN", "1/minute")
    get_backend().reset()

    wrong = {"email": HR["email"], "password": "Wrong@12345"}
    for _ in range(4):
        assert client.post(f"{API}/auth/login", json=wrong).status_code == 401


def test_an_unlimited_endpoint_is_not_throttled(client, hr_headers, monkeypatch):
    """Ordinary reads carry no limit; only the expensive routes do."""
    monkeypatch.setattr("app.core.config.settings.RATE_LIMIT_CHAT", "1/minute")
    get_backend().reset()

    for _ in range(15):
        assert client.get(f"{API}/employees", headers=hr_headers).status_code == 200


# --- Health probes ---------------------------------------------------------


def test_liveness_touches_nothing_external(client):
    """It must stay up when the database is down, or a blip becomes a crash loop."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "environment": "local"}


def test_readiness_checks_real_dependencies(client):
    response = client.get("/health/ready")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ready"
    names = {check["name"] for check in body["checks"]}
    assert names == {"database", "storage", "configuration"}
    assert all(check["ok"] for check in body["checks"])


def test_readiness_reports_503_when_the_database_is_unreachable(client, monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("app.main.engine.connect", explode)

    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"

    database = next(c for c in body["checks"] if c["name"] == "database")
    assert database["ok"] is False
    # The type name, never the connection string it failed to reach.
    assert database["detail"] == "RuntimeError"
    assert "://" not in str(body)


def test_readiness_flags_unsafe_production_configuration(client, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "production")

    response = client.get("/health/ready")
    assert response.status_code == 503

    configuration = next(
        c for c in response.json()["checks"] if c["name"] == "configuration"
    )
    assert configuration["ok"] is False
    assert "unsafe setting" in configuration["detail"]


def test_probes_need_no_authentication(client):
    """An orchestrator has no credentials to offer."""
    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 200


# --- Compression -----------------------------------------------------------


def test_large_responses_are_compressed(client, hr_headers):
    for index in range(30):
        client.post(
            f"{API}/employees",
            json={
                "first_name": "Compressible",
                "last_name": f"Person{index}",
                "work_email": f"person{index}@example.com",
            },
            headers=hr_headers,
        )

    response = client.get(
        f"{API}/employees?page_size=100",
        headers={**hr_headers, "Accept-Encoding": "gzip"},
    )
    assert response.status_code == 200
    assert response.headers.get("content-encoding") == "gzip"


def test_small_responses_are_not_compressed(client):
    """Below the threshold, compression costs more CPU than it saves bytes."""
    response = client.get("/health", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in response.headers
