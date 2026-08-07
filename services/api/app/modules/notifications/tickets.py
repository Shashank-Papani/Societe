"""Short-lived one-time realtime tickets (hashed in Valkey).

Tickets are purpose-scoped: a ticket issued for ``notifications`` cannot
authenticate ``calling_cards`` (or vice versa).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from typing import Literal
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.errors import AppError
from app.db.session import get_redis
from app.modules.notifications.schemas import RealtimeAuthenticateMessage

RealtimePurpose = Literal["notifications", "calling_cards"]

REALTIME_PURPOSES: frozenset[str] = frozenset({"notifications", "calling_cards"})

WEBSOCKET_PATH_BY_PURPOSE: dict[RealtimePurpose, str] = {
    "notifications": "/v1/realtime/notifications",
    "calling_cards": "/v1/realtime/ws",
}

TICKET_PREFIX = "realtime:ticket:"
CONN_PREFIX = "realtime:notif-conn:"


def _hash_ticket(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def websocket_path_for_purpose(purpose: RealtimePurpose) -> str:
    return WEBSOCKET_PATH_BY_PURPOSE[purpose]


def parse_realtime_purpose(value: str) -> RealtimePurpose:
    if value not in REALTIME_PURPOSES:
        raise AppError(
            "REALTIME_TICKET_INVALID",
            "Realtime ticket purpose is invalid.",
            status_code=400,
        )
    return value  # type: ignore[return-value]


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
    purpose: RealtimePurpose,
) -> tuple[str, int]:
    if purpose not in REALTIME_PURPOSES:
        raise AppError(
            "REALTIME_TICKET_INVALID",
            "Realtime ticket purpose is invalid.",
            status_code=400,
        )
    await rate_limit_ticket_creation(redis, user_id=user_id)
    ttl = int(settings.notification_realtime_ticket_ttl_seconds)
    ticket = secrets.token_urlsafe(32)
    key = TICKET_PREFIX + _hash_ticket(ticket)
    # Store owner + purpose; never store the plaintext ticket.
    await redis.set(key, f"{user_id}:{purpose}", ex=ttl, nx=True)
    return ticket, ttl


async def consume_realtime_ticket(
    redis: Redis[str],
    *,
    ticket: str,
    purpose: RealtimePurpose,
) -> UUID:
    if not ticket or len(ticket) < 16:
        raise AppError("REALTIME_TICKET_INVALID", "Realtime ticket is invalid.", status_code=401)
    key = TICKET_PREFIX + _hash_ticket(ticket)
    # Atomic consume — reuse is impossible after getdel.
    raw = await redis.getdel(key)
    if raw is None:
        raise AppError(
            "REALTIME_TICKET_EXPIRED",
            "Realtime ticket is expired or already used.",
            status_code=401,
        )
    try:
        user_raw, stored_purpose = raw.split(":", 1)
    except ValueError as exc:
        raise AppError(
            "REALTIME_TICKET_INVALID",
            "Realtime ticket is invalid.",
            status_code=401,
        ) from exc
    if stored_purpose != purpose:
        raise AppError(
            "REALTIME_TICKET_INVALID",
            "Realtime ticket purpose mismatch.",
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


async def authenticate_websocket_with_ticket(
    websocket: WebSocket,
    *,
    settings: Settings,
    purpose: RealtimePurpose,
) -> UUID:
    """Accept the socket, then require a first-message one-time ticket.

    The ticket must never appear in the WebSocket URL (proxy/access logs).
    Query ``ticket`` / ``access_token`` are rejected. No user-specific payloads
    are sent before successful authentication.
    """
    if websocket.query_params.get("ticket") or websocket.query_params.get("access_token"):
        await websocket.close(code=4401)
        raise AppError("REALTIME_TICKET_INVALID", "Realtime ticket is invalid.", status_code=401)

    await websocket.accept()
    timeout = float(settings.notification_ws_auth_timeout_seconds)
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=timeout)
    except TimeoutError as exc:
        await websocket.close(code=4401)
        raise AppError(
            "REALTIME_TICKET_EXPIRED",
            "Realtime authentication timed out.",
            status_code=401,
        ) from exc
    except WebSocketDisconnect as exc:
        raise AppError(
            "REALTIME_TICKET_INVALID",
            "Realtime ticket is invalid.",
            status_code=401,
        ) from exc

    try:
        payload = json.loads(raw)
        auth = RealtimeAuthenticateMessage.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        await websocket.close(code=4401)
        raise AppError(
            "REALTIME_TICKET_INVALID",
            "Realtime ticket is invalid.",
            status_code=401,
        ) from exc

    redis = get_redis(settings)
    try:
        return await consume_realtime_ticket(redis, ticket=auth.ticket, purpose=purpose)
    except AppError:
        await websocket.close(code=4401)
        raise


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
