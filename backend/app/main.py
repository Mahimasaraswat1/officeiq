"""OfficeIQ API entrypoint."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel
from sqlalchemy import text

from app.api.v1 import api_router
from app.core.config import settings
from app.core.database import engine
from app.core.errors import register_exception_handlers
from app.core.middleware import (
    RequestContextMiddleware,
    RequestIdFilter,
    SecurityHeadersMiddleware,
)
from app.services.embeddings import get_embedder

DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-8s [%(request_id)s] %(name)s: %(message)s",
)
# The filter has to be on the handlers, not a logger: a record created by any
# logger must carry request_id by the time the formatter sees it, or the
# format string above raises for records from third-party libraries.
for _handler in logging.getLogger().handlers:
    _handler.addFilter(RequestIdFilter())

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description=(
        "AI-Powered HR Onboarding Automation & Team Knowledge Hub.\n\n"
        "Authentication and RBAC, employee profiles and the invitation flow, document "
        "upload with OCR extraction, mock ID verification and face matching, the HR "
        "review workflow, rule-driven task assignment, a RAG assistant over the company "
        "knowledge base, the HR analytics dashboard with search and notifications, and "
        "Excel/PDF/CSV reporting."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# --- Middleware -------------------------------------------------------------
# Starlette applies these in reverse registration order on the way in, so the
# last one added is the outermost. Request context is registered last on
# purpose: it must wrap everything, so every log line carries the request id
# and every response gets the header — including error responses produced
# deeper in the stack.

app.add_middleware(GZipMiddleware, minimum_size=settings.GZIP_MIN_SIZE_BYTES)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", settings.REQUEST_ID_HEADER],
)

app.add_middleware(SecurityHeadersMiddleware, docs_paths=DOCS_PATHS)

if settings.ALLOWED_HOSTS and settings.ALLOWED_HOSTS != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

app.add_middleware(RequestContextMiddleware)

# Say at boot what will silently fail at request time. A keyless chat provider
# is not fatal outside production — the rest of the app is unaffected — but it
# must not be discoverable only by asking the assistant a question.
for _problem in settings.provider_problems():
    logging.getLogger("app.startup").warning("CONFIGURATION: %s", _problem)

# The embedder is resolved eagerly and deliberately allowed to raise. A
# mis-set embeddings provider does not degrade search, it silently breaks it,
# so the process refuses to start rather than serve zero results that look
# like an empty knowledge base.
get_embedder()

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# --- Health -----------------------------------------------------------------


class HealthStatus(BaseModel):
    status: str
    environment: str


class DependencyCheck(BaseModel):
    name: str
    ok: bool
    detail: str | None = None


class ReadinessStatus(BaseModel):
    status: str
    environment: str
    checks: list[DependencyCheck]


@app.get("/health", tags=["System"], summary="Liveness probe", response_model=HealthStatus)
def health() -> HealthStatus:
    """Is the process alive?

    Deliberately touches nothing external. A liveness probe that queries the
    database restarts a healthy container whenever the database blips, which
    turns a recoverable outage into a crash loop.
    """
    return HealthStatus(status="ok", environment=settings.ENVIRONMENT)


@app.get(
    "/health/ready",
    tags=["System"],
    summary="Readiness probe",
    response_model=ReadinessStatus,
    responses={503: {"model": ReadinessStatus}},
)
def readiness(response: Response) -> ReadinessStatus:
    """Can this instance actually serve traffic?

    Checks the dependencies a request would need, and returns 503 when one is
    missing so a load balancer stops sending work here rather than serving
    errors to users. Failure detail is included because this endpoint is for
    operators — it names which dependency is down, never a credential.
    """
    checks: list[DependencyCheck] = []

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        checks.append(DependencyCheck(name="database", ok=True))
    except Exception as exc:  # noqa: BLE001 - the probe must report, not raise
        checks.append(
            DependencyCheck(name="database", ok=False, detail=type(exc).__name__)
        )

    try:
        from app.services.storage import get_storage

        get_storage()
        checks.append(DependencyCheck(name="storage", ok=True))
    except Exception as exc:  # noqa: BLE001
        checks.append(
            DependencyCheck(name="storage", ok=False, detail=type(exc).__name__)
        )

    # Configuration is a dependency too: a production process running on stub
    # providers is "up" but cannot do its job.
    problems = settings.production_problems() if settings.is_production else []
    checks.append(
        DependencyCheck(
            name="configuration",
            ok=not problems,
            detail=f"{len(problems)} unsafe setting(s)" if problems else None,
        )
    )

    ready = all(check.ok for check in checks)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessStatus(
        status="ready" if ready else "not_ready",
        environment=settings.ENVIRONMENT,
        checks=checks,
    )


@app.get("/", tags=["System"], include_in_schema=False)
def root() -> dict[str, str]:
    return {"service": settings.APP_NAME, "docs": "/docs", "health": "/health"}
