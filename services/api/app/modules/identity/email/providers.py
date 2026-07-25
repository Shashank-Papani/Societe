from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage as SmtpEmailMessage

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.modules.identity.email.protocol import EmailMessage

logger = get_logger(__name__)


class MemoryEmailSender:
    """In-process sink for unit tests. Never used outside development/test."""

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.messages.append(message)


class SmtpMailpitSender:
    def __init__(self, settings: Settings) -> None:
        self._host = settings.mailpit_smtp_host
        self._port = settings.mailpit_smtp_port
        self._from = "noreply@societe.local"

    async def send(self, message: EmailMessage) -> None:
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: EmailMessage) -> None:
        msg = SmtpEmailMessage()
        msg["Subject"] = message.subject
        msg["From"] = self._from
        msg["To"] = message.to_address
        msg.set_content(message.text_body)
        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
                smtp.send_message(msg)
        except OSError as exc:
            logger.error("email_send_failed", provider="mailpit")
            raise AppError(
                "EMAIL_DELIVERY_FAILED",
                "Unable to deliver email right now.",
                status_code=503,
            ) from exc


class SesEmailSender:
    """Production SES path. Credentials come from the environment / IAM role."""

    def __init__(self, settings: Settings) -> None:
        self._region = settings.ses_region
        self._from = settings.ses_from_email

    async def send(self, message: EmailMessage) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise AppError(
                "EMAIL_PROVIDER_MISCONFIGURED",
                "SES client libraries are not available.",
                status_code=500,
            ) from exc

        def _send() -> None:
            client = boto3.client("ses", region_name=self._region)
            client.send_email(
                Source=self._from,
                Destination={"ToAddresses": [message.to_address]},
                Message={
                    "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": message.text_body, "Charset": "UTF-8"}},
                },
            )

        try:
            await asyncio.to_thread(_send)
        except Exception as exc:
            logger.error("email_send_failed", provider="ses")
            raise AppError(
                "EMAIL_DELIVERY_FAILED",
                "Unable to deliver email right now.",
                status_code=503,
            ) from exc
