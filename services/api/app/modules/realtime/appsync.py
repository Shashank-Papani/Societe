"""AppSync Events stub. Production wiring is a later phase (no apply / secrets)."""

from __future__ import annotations

from typing import Any

from app.core.config import Settings


class AppSyncRealtimePublisher:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def publish(
        self,
        channel: str,
        *,
        event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        msg = (
            "AppSyncRealtimePublisher is not implemented in this phase. "
            f"Set REALTIME_PROVIDER=local (app_env={self._settings.app_env!r})."
        )
        raise NotImplementedError(msg)
