"""Short-lived one-time realtime tickets (hashed in Valkey)."""

from __future__ import annotations

import hashlib
import secrets
from uuid import UUID

from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import AppError

TICKET_PREFIX = "realtime:ticket:"
CONN_PREFIX = "realtime:notif-conn:"


def _hash_ticket(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


async def rate_limit_ticket_creation(
    redis: Redis[str], *, user_id: UUID, limit: int = 60, window: int = 60
) -> None:
    key = f"ratelimit:realtime-ticket:{user_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window)
    if count > limit:
        raise AppError(
            "REALTIME_TICKET_INVALID",
            "Too many realtime ticket requests.",
            status_code=429,
        )


async def create_realtime_ticket(
    redis: Redis[str],
    *,
    user_id: UUID,
    settings: Settings,
) -> tuple[str, int]:
    await rate_limit_ticket_creation(redis, user_id=user_id)
    ttl = int(settings.notification_realtime_ticket_ttl_seconds)
    ticket = secrets.token_urlsafe(32)
    key = TICKET_PREFIX + _hash_ticket(ticket)
    await redis.set(key, str(user_id), ex=ttl, nx=True)
    return ticket, ttl


async def consume_realtime_ticket(redis: Redis[str], *, ticket: str) -> UUID:
    if not ticket or len(ticket) < 16:
        raise AppError("REALTIME_TICKET_INVALID", "Realtime ticket is invalid.", status_code=401)
    key = TICKET_PREFIX + _hash_ticket(ticket)
    user_raw = await redis.getdel(key)
    if user_raw is None:
        raise AppError(
            "REALTIME_TICKET_EXPIRED",
            "Realtime ticket is expired or already used.",
            status_code=401,
        )
    try:
        return UUID(user_raw)
    except ValueError as exc:
        raise AppError(
            "REALTIME_TICKET_INVALID",
            "Realtime ticket is invalid.",
            status_code=401,
        ) from exc


async def acquire_notification_connection_slot(
    redis: Redis[str],
    *,
    user_id: UUID,
    connection_id: str,
    settings: Settings,
    ttl_seconds: int = 120,
) -> None:
    max_conn = int(settings.notification_ws_max_connections_per_user)
    key = CONN_PREFIX + str(user_id)
    count = await redis.scard(key)
    if count >= max_conn:
        raise AppError(
            "REALTIME_CONNECTION_LIMIT",
            "Too many realtime notification connections.",
            status_code=429,
        )
    await redis.sadd(key, connection_id)
    await redis.expire(key, ttl_seconds)


async def release_notification_connection_slot(
    redis: Redis[str], *, user_id: UUID, connection_id: str
) -> None:
    key = CONN_PREFIX + str(user_id)
    await redis.srem(key, connection_id)


def notifications_channel(user_id: UUID) -> str:
    return f"realtime:notifications:{user_id}"
