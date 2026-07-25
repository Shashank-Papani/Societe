"""In-process realtime and push adapters for local development and tests.

``LocalRealtimeHub`` records publishes for assertions and fans out over Valkey
pubsub so Compose ``event-dispatcher`` (separate process) can reach WebSocket
clients connected to the API at ``WS /v1/realtime/ws``.

Clients must deduplicate by ``event_id`` (at-least-once delivery).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis


def valkey_channel(user_channel: str) -> str:
    """Map logical ``user:{id}`` to the Valkey pubsub topic."""
    return f"realtime:{user_channel}"


@dataclass
class PublishedRealtimeEvent:
    channel: str
    event_id: str
    event_type: str
    payload: dict[str, Any]


@dataclass
class PublishedPush:
    user_id: str
    event_id: str
    event_type: str
    payload: dict[str, Any]


@dataclass
class LocalRealtimeHub:
    """Local realtime sink with event-id dedupe and optional Valkey fan-out."""

    events: list[PublishedRealtimeEvent] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)
    _redis: Redis[str] | None = None

    def bind_redis(self, redis: Redis[str]) -> None:
        self._redis = redis

    def clear(self) -> None:
        self.events.clear()
        self._seen.clear()

    async def publish(
        self,
        channel: str,
        *,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        dedupe_key = f"{channel}:{event_id}"
        if dedupe_key in self._seen:
            return
        self._seen.add(dedupe_key)

        envelope = {
            "channel": channel,
            "event_id": event_id,
            "event_type": event_type,
            "payload": dict(payload),
        }
        self.events.append(
            PublishedRealtimeEvent(
                channel=channel,
                event_id=event_id,
                event_type=event_type,
                payload=dict(payload),
            )
        )
        if self._redis is not None:
            await self._redis.publish(valkey_channel(channel), json.dumps(envelope))


@dataclass
class LocalPushPublisher:
    """Records push calls for tests. No APNs/FCM credentials."""

    calls: list[PublishedPush] = field(default_factory=list)

    async def publish(
        self,
        *,
        user_id: str,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.calls.append(
            PublishedPush(
                user_id=user_id,
                event_id=event_id,
                event_type=event_type,
                payload=dict(payload),
            )
        )

    def clear(self) -> None:
        self.calls.clear()


class NoopPushPublisher:
    async def publish(
        self,
        *,
        user_id: str,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        return None
