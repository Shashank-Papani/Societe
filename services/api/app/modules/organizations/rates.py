"""Organization claim and invitation rate limits (fail closed)."""

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


class OrganizationRateLimiter:
    def __init__(self, redis: Redis[str], settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    async def _incr(self, key: str, *, ttl_seconds: int) -> int:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_seconds)
        results = await pipe.execute()
        return int(results[0])

    async def check_claim(self, *, user_id: UUID, now: datetime) -> None:
        window = int(now.timestamp()) // HOUR
        key = f"rate:user:{user_id}:venue_claim:{window}"
        try:
            count = await self._incr(key, ttl_seconds=HOUR * 2)
        except RedisError as exc:
            logger.error("venue_claim_rate_limit_unavailable")
            raise AppError(
                "VENUE_CLAIM_RATE_LIMIT_UNAVAILABLE",
                "Rate limiting is unavailable; try again shortly.",
                status_code=503,
            ) from exc
        if count > self._settings.venue_claim_rate_limit_per_user_per_hour:
            raise AppError(
                "VENUE_CLAIM_RATE_LIMITED",
                "Too many venue claims. Try again later.",
                status_code=429,
            )

    async def check_invitation(self, *, organization_id: UUID, now: datetime) -> None:
        window = int(now.timestamp()) // HOUR
        key = f"rate:org:{organization_id}:invitation:{window}"
        try:
            count = await self._incr(key, ttl_seconds=HOUR * 2)
        except RedisError as exc:
            logger.error("org_invitation_rate_limit_unavailable")
            raise AppError(
                "ORGANIZATION_INVITATION_RATE_LIMIT_UNAVAILABLE",
                "Rate limiting is unavailable; try again shortly.",
                status_code=503,
            ) from exc
        if count > self._settings.organization_invitation_rate_limit_per_org_per_hour:
            raise AppError(
                "ORGANIZATION_INVITATION_RATE_LIMITED",
                "Too many invitations. Try again later.",
                status_code=429,
            )
