"""Publish safe notification hints to Valkey for the notifications WebSocket."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from app.modules.notifications.tickets import notifications_channel


async def publish_notification_hint(
    redis: Redis[str],
    *,
    user_id: UUID,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    envelope = {
        "type": event_type,
        "payload": payload,
    }
    await redis.publish(notifications_channel(user_id), json.dumps(envelope, default=str))
