"""Request-scoped middleware: correlation IDs, access logging, security headers
(PRD B.5 / B.8).

Ordering matters and is set in `main.py`. Starlette runs middleware in reverse
registration order on the way in, so the request-ID layer is added last and
therefore runs first — every log line and every error response that follows can
carry the id.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import settings

logger = logging.getLogger("app.access")

# Readable by the logging filter below and by anything else that wants to
# attach the current request's id without threading it through call signatures.
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def current_request_id() -> str:
    return request_id_ctx.get()


class RequestIdFilter(logging.Filter):
    """Puts the request id on every record, so `%(request_id)s` always resolves."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id()
        return True


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id, time the request, and log the outcome.

    A client-supplied id is honoured so a trace can span the frontend, a proxy
    and this service — but it is length-capped and sanitised, because it ends up
    in log lines and a response header.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        incoming = request.headers.get(settings.REQUEST_ID_HEADER, "")
        cleaned = "".join(c for c in incoming if c.isalnum() or c in "-_")[:64]
        request_id = cleaned or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # The exception handlers turn this into a 500 envelope; log the
            # timing here so a crash still produces an access line.
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "%s %s failed after %.0fms", request.method, request.url.path, elapsed_ms
            )
            request_id_ctx.reset(token)
            raise

        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers[settings.REQUEST_ID_HEADER] = request_id
        # Give the browser a way to read the id back for a bug report.
        response.headers["Access-Control-Expose-Headers"] = ", ".join(
            filter(
                None,
                [
                    response.headers.get("Access-Control-Expose-Headers"),
                    settings.REQUEST_ID_HEADER,
                ],
            )
        )

        # The route pattern, not the resolved path, so per-endpoint timings
        # aggregate instead of scattering across every uuid.
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        log = logger.warning if elapsed_ms >= settings.SLOW_REQUEST_MS else logger.info
        log(
            "%s %s -> %s in %.0fms",
            request.method,
            route_path,
            response.status_code,
            elapsed_ms,
        )

        request_id_ctx.reset(token)
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds the response headers a browser needs to defend the user.

    This is a JSON API, not a page server, so the policy is maximally strict:
    nothing is embeddable, nothing is sniffable, and the default CSP forbids
    every source. The interactive docs are the one exception — they load Swagger
    from a CDN, so a CSP that blocked it would break the documentation rather
    than protect anybody.
    """

    def __init__(self, app: ASGIApp, docs_paths: tuple[str, ...] = ()) -> None:
        super().__init__(app)
        self.docs_paths = docs_paths

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        # API responses are never rendered as a document, so nothing needs to load.
        if request.url.path not in self.docs_paths:
            response.headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )

        # HSTS only over a connection that is already secure — sending it over
        # plain http is meaningless, and in local development it would pin
        # localhost to https in the developer's browser for a year.
        if settings.is_production and request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={settings.HSTS_MAX_AGE_SECONDS}; includeSubDomains",
            )
        return response
