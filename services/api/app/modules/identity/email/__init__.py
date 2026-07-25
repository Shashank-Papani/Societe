from __future__ import annotations

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.identity.email.protocol import EmailMessage, EmailSender
from app.modules.identity.email.providers import (
    MemoryEmailSender,
    SesEmailSender,
    SmtpMailpitSender,
)

_MEMORY_SENDER: MemoryEmailSender | None = None


def build_email_sender(settings: Settings) -> EmailSender:
    """Fail closed: never silently fall back across environments (ADR 0018)."""
    if settings.email_provider == "mailpit":
        if settings.app_env not in {"development", "test"}:
            raise AppError(
                "EMAIL_PROVIDER_MISCONFIGURED",
                "Mailpit email is only available in development/test.",
                status_code=500,
            )
        return SmtpMailpitSender(settings)
    if settings.email_provider == "memory":
        if settings.app_env not in {"development", "test"}:
            raise AppError(
                "EMAIL_PROVIDER_MISCONFIGURED",
                "Memory email is only available in development/test.",
                status_code=500,
            )
        global _MEMORY_SENDER
        if _MEMORY_SENDER is None:
            _MEMORY_SENDER = MemoryEmailSender()
        return _MEMORY_SENDER
    if settings.email_provider == "ses":
        if not settings.ses_from_email:
            raise AppError(
                "EMAIL_PROVIDER_MISCONFIGURED",
                "SES_FROM_EMAIL is required for EMAIL_PROVIDER=ses.",
                status_code=500,
            )
        return SesEmailSender(settings)
    raise AppError(
        "EMAIL_PROVIDER_MISCONFIGURED",
        "Configured email provider is invalid.",
        status_code=500,
    )


def reset_memory_email_sender() -> None:
    global _MEMORY_SENDER
    _MEMORY_SENDER = None


__all__ = [
    "EmailMessage",
    "EmailSender",
    "build_email_sender",
    "reset_memory_email_sender",
]
