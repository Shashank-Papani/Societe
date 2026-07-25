"""Realtime delivery acknowledgements stored in Valkey.

Clients call ``POST /v1/events/{event_id}/ack`` after receiving a realtime
envelope. The event_dispatcher waits briefly, then requests push fallback when
the key is still missing (architecture: no ack → push).
"""

from __future__ import annotations

from redis.asyncio import Redis

ACK_KEY_PREFIX = "realtime:ack:"


def ack_key(event_id: str) -> str:
    return f"{ACK_KEY_PREFIX}{event_id}"


async def record_event_ack(
    redis: Redis[str],
    *,
    event_id: str,
    ttl_seconds: int,
) -> None:
    await redis.set(ack_key(event_id), "1", ex=ttl_seconds)


async def has_event_ack(redis: Redis[str], *, event_id: str) -> bool:
    return bool(await redis.exists(ack_key(event_id)))
