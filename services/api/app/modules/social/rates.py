"""Calling Card rate limits.

Unlike location ingest, these fail **closed**: sending a card already requires a
live Valkey lease, so an outage must not open the door to spam.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

TEN_MINUTES = 600


class CallingCardRateLimiter:
    def __init__(self, redis: Redis[str], settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    @staticmethod
    def _ten_minute_window(now: datetime) -> int:
        return int(now.timestamp()) // TEN_MINUTES

    async def _incr(self, key: str, *, ttl_seconds: int) -> int:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_seconds)
        results = await pipe.execute()
        return int(results[0])

    async def check_send(
        self,
        *,
        user_id: UUID,
        venue_id: UUID,
        venue_night: str,
        now: datetime,
    ) -> None:
        window = self._ten_minute_window(now)
        retry_after = TEN_MINUTES - int(now.timestamp()) % TEN_MINUTES
        buckets = (
            (
                f"rate:user:{user_id}:calling_card:{window}",
                self._settings.calling_card_rate_limit_per_user_per_10_minutes,
                TEN_MINUTES * 2,
                "user_10m",
                retry_after,
            ),
            (
                f"rate:user:{user_id}:venue:{venue_id}:calling_card_night:{venue_night}",
                self._settings.calling_card_rate_limit_per_user_per_venue_night,
                36 * 3600,
                "user_venue_night",
                3600,
            ),
        )
        for key, limit, ttl, scope, retry in buckets:
            try:
                count = await self._incr(key, ttl_seconds=ttl)
            except RedisError as exc:
                logger.error("calling_card_rate_limit_unavailable", scope=scope)
                raise AppError(
                    "CALLING_CARD_RATE_LIMIT_UNAVAILABLE",
                    "Rate limiting is unavailable; try again shortly.",
                    status_code=503,
                ) from exc
            if count > limit:
                raise AppError(
                    "CALLING_CARD_RATE_LIMITED",
                    "Too many Calling Cards. Try again later.",
                    status_code=429,
                    details={"scope": scope, "retry_after_seconds": retry},
                )
