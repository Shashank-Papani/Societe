"""Message send rate limits (fail closed, same pattern as Calling Cards)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

ONE_MINUTE = 60


class MessageRateLimiter:
    def __init__(self, redis: Redis[str], settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    @staticmethod
    def _minute_window(now: datetime) -> int:
        return int(now.timestamp()) // ONE_MINUTE

    async def _incr(self, key: str, *, ttl_seconds: int) -> int:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_seconds)
        results = await pipe.execute()
        return int(results[0])

    async def check_send(self, *, user_id: UUID, now: datetime) -> None:
        window = self._minute_window(now)
        retry_after = ONE_MINUTE - int(now.timestamp()) % ONE_MINUTE
        key = f"rate:user:{user_id}:message:{window}"
        try:
            count = await self._incr(key, ttl_seconds=ONE_MINUTE * 2)
        except RedisError as exc:
            logger.error("message_rate_limit_unavailable")
            raise AppError(
                "MESSAGE_RATE_LIMIT_UNAVAILABLE",
                "Rate limiting is unavailable; try again shortly.",
                status_code=503,
            ) from exc
        if count > self._settings.message_rate_limit_per_user_per_minute:
            raise AppError(
                "MESSAGE_RATE_LIMITED",
                "Too many messages. Try again later.",
                status_code=429,
                details={"scope": "user_1m", "retry_after_seconds": retry_after},
            )
