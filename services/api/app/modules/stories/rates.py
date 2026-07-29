"""Story and official-content rate limits (fail closed on Valkey errors)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

HOUR = 3600


class StoryRateLimiter:
    def __init__(self, redis: Redis[str], settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    @staticmethod
    def _window(now: datetime) -> int:
        return int(now.timestamp()) // HOUR

    async def _incr(self, key: str) -> int:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, HOUR * 2)
        results = await pipe.execute()
        return int(results[0])

    async def _consume(self, buckets: tuple[tuple[str, int, str], ...], now: datetime) -> None:
        retry_after = HOUR - int(now.timestamp()) % HOUR
        for key, limit, scope in buckets:
            try:
                count = await self._incr(key)
            except RedisError as exc:
                logger.error("story_rate_limit_unavailable", scope=scope)
                raise AppError(
                    "STORY_RATE_LIMIT_UNAVAILABLE",
                    "Rate limiting is unavailable; try again shortly.",
                    status_code=503,
                ) from exc
            if count > limit:
                raise AppError(
                    "STORY_RATE_LIMITED",
                    "Too many requests. Try again later.",
                    status_code=429,
                    details={"scope": scope, "retry_after_seconds": retry_after},
                )

    async def check_user_story_intent(self, *, user_id: UUID, now: datetime) -> None:
        window = self._window(now)
        await self._consume(
            (
                (
                    f"rate:user:{user_id}:story_upload:{window}",
                    self._settings.story_upload_rate_limit_per_user_per_hour,
                    "user_story",
                ),
            ),
            now,
        )

    async def check_official_story_intent(self, *, organization_id: UUID, now: datetime) -> None:
        window = self._window(now)
        await self._consume(
            (
                (
                    f"rate:org:{organization_id}:official_story_upload:{window}",
                    self._settings.official_story_upload_rate_limit_per_org_per_hour,
                    "official_story",
                ),
            ),
            now,
        )

    async def check_official_post(self, *, organization_id: UUID, now: datetime) -> None:
        window = self._window(now)
        await self._consume(
            (
                (
                    f"rate:org:{organization_id}:official_post:{window}",
                    self._settings.official_post_rate_limit_per_org_per_hour,
                    "official_post",
                ),
            ),
            now,
        )

    async def check_report(self, *, user_id: UUID, now: datetime) -> None:
        window = self._window(now)
        await self._consume(
            (
                (
                    f"rate:user:{user_id}:story_report:{window}",
                    self._settings.story_report_rate_limit_per_user_per_hour,
                    "story_report",
                ),
            ),
            now,
        )

    async def check_view_soft(self, *, user_id: UUID, now: datetime) -> None:
        """Soft view budget — high enough for normal Story progression."""
        window = self._window(now)
        limit = max(self._settings.story_upload_rate_limit_per_user_per_hour * 40, 500)
        await self._consume(
            (
                (
                    f"rate:user:{user_id}:story_view:{window}",
                    limit,
                    "story_view",
                ),
            ),
            now,
        )
