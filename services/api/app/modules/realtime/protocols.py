from __future__ import annotations

from typing import Any, Protocol


class RealtimePublisher(Protocol):
    async def publish(
        self,
        channel: str,
        *,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Publish an event to a user-scoped channel. At-least-once delivery."""


class PushPublisher(Protocol):
    async def publish(
        self,
        *,
        user_id: str,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """Best-effort push fallback after a missed realtime ack."""
