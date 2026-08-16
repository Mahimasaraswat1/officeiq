"""Transactional email with a pluggable backend.

Phase 1 ships `console` and `file` backends so the whole invitation flow is
testable without credentials. `smtp` is wired to the same interface so switching
in Phase 8 is a config change, not a code change (PRD B.2 / B.5).
"""

from __future__ import annotations

import logging
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    body: str


class EmailBackend:
    def send(self, message: OutgoingEmail) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleEmailBackend(EmailBackend):
    """Logs the message. Useful when tailing the dev server."""

    def send(self, message: OutgoingEmail) -> None:
        logger.info(
            "[email:console] to=%s subject=%s\n%s",
            message.to,
            message.subject,
            message.body,
        )


class FileEmailBackend(EmailBackend):
    """Writes each message to ./outbox as a readable .txt file."""

    def __init__(self, directory: str) -> None:
        self.directory = Path(directory)

    def send(self, message: OutgoingEmail) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        safe_to = _SAFE_FILENAME.sub("_", message.to)
        path = self.directory / f"{stamp}__{safe_to}.txt"
        path.write_text(
            f"From: {settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>\n"
            f"To: {message.to}\n"
            f"Subject: {message.subject}\n"
            f"{'-' * 72}\n"
            f"{message.body}\n",
            encoding="utf-8",
        )
        logger.info("[email:file] wrote %s", path)


class SmtpEmailBackend(EmailBackend):
    def __init__(self) -> None:
        if not settings.SMTP_HOST:
            raise RuntimeError("EMAIL_BACKEND=smtp requires SMTP_HOST to be set")

    def send(self, message: OutgoingEmail) -> None:
        msg = EmailMessage()
        msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
        msg["To"] = message.to
        msg["Subject"] = message.subject
        msg.set_content(message.body)

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        logger.info("[email:smtp] sent to %s", message.to)


def get_email_backend() -> EmailBackend:
    if settings.EMAIL_BACKEND == "smtp":
        return SmtpEmailBackend()
    if settings.EMAIL_BACKEND == "console":
        return ConsoleEmailBackend()
    return FileEmailBackend(settings.EMAIL_OUTBOX_DIR)


def send_email(to: str, subject: str, body: str) -> None:
    """Send a message, never letting a delivery failure break the request."""
    try:
        get_email_backend().send(OutgoingEmail(to=to, subject=subject, body=body))
    except Exception:  # noqa: BLE001 - email must not fail the calling operation
        logger.exception("Failed to send email to %s (subject=%s)", to, subject)


# --- Templates -------------------------------------------------------------


def send_invitation_email(
    *, to: str, employee_name: str, token: str, expires_at: datetime
) -> str:
    """Send the onboarding invite and return the link (handy for tests/dev)."""
    link = f"{settings.FRONTEND_BASE_URL}/accept-invite?token={token}"
    body = (
        f"Hi {employee_name},\n\n"
        "Welcome aboard! Your onboarding profile has been created in OfficeIQ.\n\n"
        "Set your password and complete your onboarding here:\n"
        f"{link}\n\n"
        f"This link expires on {expires_at:%d %b %Y, %H:%M UTC}.\n"
        "If you weren't expecting this email, you can safely ignore it.\n\n"
        "— The OfficeIQ Team"
    )
    send_email(to=to, subject="Complete your OfficeIQ onboarding", body=body)
    return link


def send_password_reset_email(*, to: str, name: str, token: str, expires_at: datetime) -> str:
    link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={token}"
    body = (
        f"Hi {name},\n\n"
        "We received a request to reset your OfficeIQ password.\n\n"
        f"{link}\n\n"
        f"This link expires on {expires_at:%d %b %Y, %H:%M UTC}.\n"
        "If you did not request this, no action is needed — your password is unchanged.\n\n"
        "— The OfficeIQ Team"
    )
    send_email(to=to, subject="Reset your OfficeIQ password", body=body)
    return link
