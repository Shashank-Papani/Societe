"""Push token hashing, fake provider, and delivery claiming."""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Notification, NotificationDelivery, NotificationPreference, UserDevice
from app.modules.notifications.constants import CATEGORY_DEFAULTS, category_for_type

_EXPO_TOKEN_RE = re.compile(r"^(ExponentPushToken\[.+\]|[A-Za-z0-9_-]{16,})$")


def hash_push_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_suffix(token: str) -> str:
    return token[-8:] if len(token) >= 8 else token


def validate_expo_token(token: str) -> None:
    cleaned = token.strip()
    if not cleaned or not _EXPO_TOKEN_RE.match(cleaned):
        raise AppError("PUSH_TOKEN_INVALID", "Push token is malformed.", status_code=400)


@dataclass
class PushSendResult:
    ok: bool
    permanent: bool
    provider_message_id: str | None
    error_code: str | None


class FakePushProvider:
    """Local/test provider — never talks to APNs/FCM/Expo.

    Phase 9A intentionally stores only ``push_token_hash`` + ``push_token_suffix``
    on ``user_devices``. That is enough for uniqueness, conflict detection, and
    fake-provider tests, but **cannot** deliver through a real Expo (or APNs/FCM)
    provider, which needs the plaintext token at send time.

    Production follow-up (not this phase): keep the hash for uniqueness, and store
    an encrypted token ciphertext or a secret-store reference for delivery. Never
    persist plaintext push tokens in ordinary columns, logs, outbox, or audit.
    """

    def __init__(self, *, fail_tokens: set[str] | None = None) -> None:
        self.fail_tokens = fail_tokens or set()
        self.sent: list[dict[str, str]] = []

    async def send(
        self,
        *,
        token_hash: str,
        title: str,
        body: str,
        data: dict[str, str],
    ) -> PushSendResult:
        if token_hash in self.fail_tokens or data.get("force_invalid_token") == "1":
            return PushSendResult(
                ok=False,
                permanent=True,
                provider_message_id=None,
                error_code="INVALID_TOKEN",
            )
        if data.get("force_retryable") == "1":
            return PushSendResult(
                ok=False,
                permanent=False,
                provider_message_id=None,
                error_code="TRANSIENT",
            )
        message_id = f"local-{uuid4()}"
        self.sent.append(
            {"token_hash": token_hash, "title": title, "body": body, "message_id": message_id}
        )
        return PushSendResult(
            ok=True, permanent=False, provider_message_id=message_id, error_code=None
        )


def build_push_provider(settings: Settings) -> FakePushProvider:
    _ = settings
    return FakePushProvider()


async def rate_limit_push_registration(
    redis: Redis[str], *, user_id: UUID, limit: int = 30, window: int = 3600
) -> None:
    key = f"ratelimit:push-token:{user_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window)
    if count > limit:
        raise AppError(
            "PUSH_TOKEN_INVALID",
            "Too many push token registration attempts.",
            status_code=429,
        )


def disable_device_push(device: UserDevice, *, now: datetime) -> None:
    device.push_enabled = False
    device.push_invalidated_at = now


async def create_deliveries_for_notification(
    session: AsyncSession,
    notification: Notification,
    *,
    now: datetime,
) -> list[NotificationDelivery]:
    category = category_for_type(notification.notification_type)
    pref = await session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == notification.recipient_user_id,
            NotificationPreference.category == category,
        )
    )
    push_enabled = (
        pref.push_enabled if pref is not None else CATEGORY_DEFAULTS[category]["push_enabled"]
    )
    if not push_enabled:
        return []

    devices = list(
        (
            await session.execute(
                select(UserDevice).where(
                    UserDevice.user_id == notification.recipient_user_id,
                    UserDevice.revoked_at.is_(None),
                    UserDevice.push_enabled.is_(True),
                    UserDevice.push_invalidated_at.is_(None),
                    UserDevice.push_token_hash.is_not(None),
                )
            )
        ).scalars()
    )
    created: list[NotificationDelivery] = []
    for device in devices:
        existing = await session.scalar(
            select(NotificationDelivery).where(
                NotificationDelivery.notification_id == notification.id,
                NotificationDelivery.device_id == device.id,
                NotificationDelivery.channel == "push",
            )
        )
        if existing is not None:
            continue
        row = NotificationDelivery(
            notification_id=notification.id,
            device_id=device.id,
            channel="push",
            status="pending",
            attempt_count=0,
            next_attempt_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        created.append(row)
    return created


def _backoff_seconds(attempts: int) -> float:
    ceiling = min(5 * (2 ** max(attempts - 1, 0)), 300)
    return random.uniform(0, ceiling)


async def claim_deliveries(
    session: AsyncSession,
    *,
    limit: int,
    now: datetime,
    owner: str,
    lease_seconds: int = 30,
) -> list[NotificationDelivery]:
    result = await session.execute(
        select(NotificationDelivery)
        .where(
            NotificationDelivery.status.in_(("pending", "retryable")),
            or_(
                NotificationDelivery.next_attempt_at.is_(None),
                NotificationDelivery.next_attempt_at <= now,
            ),
            or_(
                NotificationDelivery.lease_expires_at.is_(None),
                NotificationDelivery.lease_expires_at <= now,
            ),
        )
        .order_by(
            NotificationDelivery.next_attempt_at.nullsfirst(), NotificationDelivery.created_at
        )
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    rows = list(result.scalars().all())
    lease_until = now + timedelta(seconds=lease_seconds)
    for row in rows:
        row.status = "sending"
        row.lease_owner = owner
        row.lease_expires_at = lease_until
        row.updated_at = now
    return rows


async def process_delivery(
    session: AsyncSession,
    delivery: NotificationDelivery,
    *,
    provider: FakePushProvider,
    now: datetime,
) -> None:
    device = await session.get(UserDevice, delivery.device_id)
    notification = await session.get(Notification, delivery.notification_id)
    if (
        device is None
        or notification is None
        or device.revoked_at is not None
        or not device.push_enabled
        or device.push_invalidated_at is not None
        or not device.push_token_hash
    ):
        delivery.status = "cancelled"
        delivery.failed_at = now
        delivery.last_error_code = "DEVICE_UNAVAILABLE"
        delivery.lease_owner = None
        delivery.lease_expires_at = None
        delivery.updated_at = now
        return

    delivery.attempt_count += 1
    result = await provider.send(
        token_hash=device.push_token_hash,
        title=notification.title,
        body=notification.body,
        data={
            "notification_id": str(notification.id),
            "deep_link": notification.deep_link or "",
        },
    )
    if result.ok:
        delivery.status = "delivered"
        delivery.delivered_at = now
        delivery.provider_message_id = result.provider_message_id
        delivery.last_error_code = None
        device.push_last_success_at = now
        device.push_failure_count = 0
    elif result.permanent:
        delivery.status = "permanently_failed"
        delivery.failed_at = now
        delivery.last_error_code = result.error_code
        device.push_enabled = False
        device.push_invalidated_at = now
        device.push_failure_count = (device.push_failure_count or 0) + 1
    else:
        delivery.status = "retryable"
        delivery.last_error_code = result.error_code
        delivery.next_attempt_at = now + timedelta(seconds=_backoff_seconds(delivery.attempt_count))
        device.push_failure_count = (device.push_failure_count or 0) + 1
    delivery.lease_owner = None
    delivery.lease_expires_at = None
    delivery.updated_at = now
