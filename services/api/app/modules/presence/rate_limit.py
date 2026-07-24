"""Per-user and per-device location ingest limits.

Both dimensions are enforced: a per-user limit alone lets one account fan a
spoofing loop across many installations, and a per-device limit alone lets one
device rotate accounts.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

WINDOW_SECONDS = 60


class LocationRateLimiter:
    def __init__(
        self,
        redis: Redis[str],
        *,
        per_user_per_minute: int,
        per_device_per_minute: int,
    ) -> None:
        self._redis = redis
        self._per_user = per_user_per_minute
        self._per_device = per_device_per_minute

    @staticmethod
    def _window(now: datetime) -> int:
        return int(now.timestamp()) // WINDOW_SECONDS

    async def _incr(self, key: str) -> int | None:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, WINDOW_SECONDS * 2)
        results = await pipe.execute()
        return int(results[0]) if results else None

    async def check(self, *, user_id: UUID, device_id: UUID, now: datetime) -> None:
        """Raise 429 when either bucket is exhausted.

        Valkey failures fail open: the durable path already refuses to grant a
        lease without Valkey, so an outage should not also block ingestion.
        """
        window = self._window(now)
        retry_after = WINDOW_SECONDS - int(now.timestamp()) % WINDOW_SECONDS
        buckets = (
            (f"rate:user:{user_id}:location:{window}", self._per_user, "user"),
            (f"rate:device:{device_id}:location:{window}", self._per_device, "device"),
        )
        for key, limit, scope in buckets:
            try:
                count = await self._incr(key)
            except RedisError:
                logger.warning("presence_rate_limit_unavailable", scope=scope)
                return
            if count is not None and count > limit:
                raise AppError(
                    "LOCATION_RATE_LIMITED",
                    "Too many location updates. Slow down and retry shortly.",
                    status_code=429,
                    details={"scope": scope, "retry_after_seconds": retry_after},
                )
