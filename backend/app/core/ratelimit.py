"""Rate limiting for the endpoints where abuse is cheap and costly (PRD B.5).

Applied to four kinds of route:

* **sign-in** — the per-account lockout already stops one account being brute
  forced, but says nothing about one IP trying a thousand *different* accounts.
* **password reset** — unauthenticated and sends email; a loop here is a way to
  spam someone else's inbox from our domain.
* **the assistant** — every question costs a model call, in money.
* **reports** — every export scans and renders the whole table.

## The backend is in-memory, and that means something

Counters live in this process. With one worker that is exact. With N workers a
client effectively gets N times the limit, because each worker counts only what
it saw, and a restart forgets everything.

That is a deliberate trade for a v1 with no Redis dependency, and it is honest
about what it buys: it stops scripted abuse, not a distributed attacker. The
limiter sits behind `RateLimitBackend` so swapping in Redis is one class and no
call-site changes.
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Request

from app.core.config import settings
# Imported at module scope, not inside the factory below: `from __future__ import
# annotations` makes every annotation a string, and FastAPI resolves them against
# module globals. A function-local import would leave `CurrentUser` unresolvable,
# and FastAPI would silently treat the parameter as a query field.
from app.core.deps import CurrentUser
from app.core.errors import AppError

_RULE = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour|day)\s*$", re.IGNORECASE)
_WINDOWS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message, details={"retry_after_seconds": retry_after})
        self.retry_after = retry_after


@dataclass(frozen=True)
class Rule:
    limit: int
    window_seconds: int

    @classmethod
    def parse(cls, spec: str) -> "Rule":
        """Parse "10/minute". Raises on anything else — a typo in a limit must
        fail at startup, not silently disable the protection."""
        match = _RULE.match(spec)
        if not match:
            raise ValueError(
                f"Invalid rate-limit rule {spec!r}; expected e.g. '10/minute'."
            )
        return cls(int(match.group(1)), _WINDOWS[match.group(2).lower()])

    @property
    def human_window(self) -> str:
        return {1: "second", 60: "minute", 3600: "hour", 86400: "day"}[
            self.window_seconds
        ]


class RateLimitBackend:
    def hit(self, key: str, rule: Rule) -> tuple[bool, int]:  # pragma: no cover
        """Record an attempt. Returns (allowed, retry_after_seconds)."""
        raise NotImplementedError

    def reset(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class InMemoryRateLimitBackend(RateLimitBackend):
    """A sliding window of hit timestamps per key.

    Sliding rather than fixed buckets: a fixed window lets a client spend its
    whole allowance at 11:59:59 and again at 12:00:00, which is twice the limit
    in one second at exactly the moment that matters.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, rule: Rule) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - rule.window_seconds

        with self._lock:
            timestamps = self._hits[key]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= rule.limit:
                retry_after = max(1, int(timestamps[0] + rule.window_seconds - now) + 1)
                return False, retry_after

            timestamps.append(now)
            # Keys go away once their window empties, so an IP seen once does
            # not occupy memory forever.
            if not timestamps:
                del self._hits[key]
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_backend: RateLimitBackend = InMemoryRateLimitBackend()


def get_backend() -> RateLimitBackend:
    return _backend


def set_backend(backend: RateLimitBackend) -> None:
    """Swap the backend — the seam a Redis implementation plugs into."""
    global _backend
    _backend = backend


def client_key(request: Request) -> str:
    """Identify the caller: the signed-in user if known, otherwise the IP.

    Keying an authenticated route by user rather than IP means a whole office
    behind one NAT address does not share a single allowance.
    """
    user = getattr(request.state, "rate_limit_subject", None)
    if user:
        return f"user:{user}"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"
    return f"ip:{request.client.host if request.client else 'unknown'}"


def enforce(request: Request, *, bucket: str, spec: str) -> None:
    """Count this request against `bucket`, raising 429 when over the limit."""
    if not settings.RATE_LIMIT_ENABLED:
        return

    rule = Rule.parse(spec)
    allowed, retry_after = get_backend().hit(f"{bucket}:{client_key(request)}", rule)
    if not allowed:
        raise RateLimitedError(
            f"Too many requests — the limit is {rule.limit} per {rule.human_window}. "
            f"Try again in about {retry_after} second(s).",
            retry_after=retry_after,
        )


# --- Dependencies ----------------------------------------------------------


def limit(bucket: str, spec_attr: str):
    """A dependency enforcing one named limit, keyed by IP.

    For unauthenticated routes, where the IP is all we know. The setting is
    read by name at request time rather than captured at import, so limits stay
    overridable in tests without rebuilding the app.
    """

    def dependency(request: Request) -> None:
        enforce(request, bucket=bucket, spec=getattr(settings, spec_attr))

    return dependency


def limit_by_user(bucket: str, spec_attr: str):
    """A dependency enforcing one named limit, keyed by account.

    Resolving the user inside the dependency is what makes per-account keying
    possible: a decorator-level dependency would run before the endpoint's own
    auth parameter and could only see an IP. FastAPI caches `get_current_user`
    per request, so this does not authenticate twice.
    """
    def dependency(request: Request, user: CurrentUser) -> None:
        request.state.rate_limit_subject = str(user.id)
        enforce(request, bucket=bucket, spec=getattr(settings, spec_attr))

    return dependency


login_rate_limit = limit("login", "RATE_LIMIT_LOGIN")
password_reset_rate_limit = limit("password_reset", "RATE_LIMIT_PASSWORD_RESET")
chat_rate_limit = limit_by_user("chat", "RATE_LIMIT_CHAT")
report_rate_limit = limit_by_user("reports", "RATE_LIMIT_REPORTS")
