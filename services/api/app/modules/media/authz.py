"""Authorization and admission control for posting a Live Vibe.

Two separate questions, both answered here before any object key is minted:

1. *May this account post to this venue right now?* Delegated to
   ``PresenceService.can_post_live_vibe``, which reads the Valkey lease.
2. *Is this specific request within declared limits?* MIME, size, caption, tag,
   and rate limits — checked before we hand out a presigned URL, because a URL
   is a capability and we do not mint capabilities for requests we would reject.

Ghost Mode does not appear in either answer. It decides attribution only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import MediaAsset, User, UserDevice
from app.modules.media.schemas import CreateUploadRequest
from app.modules.presence.service import PresenceService

logger = get_logger(__name__)

HOUR_SECONDS = 3600

#: Presence reasons the client can act on by re-proving location.
RETRYABLE_PRESENCE_REASONS = frozenset(
    {
        "presence_refresh_required",
        "presence_provisional",
        "presence_degraded",
        "presence_cache_unavailable",
    }
)


@dataclass(frozen=True)
class UploadAuthorization:
    device: UserDevice
    venue_id: UUID
    check_in_id: UUID
    attribution_mode: str


def require_media_posting_enabled(settings: Settings) -> None:
    if not settings.ff_media_posting:
        raise AppError(
            "MEDIA_POSTING_DISABLED",
            "Live Vibe posting is not enabled.",
            status_code=403,
        )


def validate_declared_media(request: CreateUploadRequest, settings: Settings) -> None:
    """Cheap declared-value checks. The real MIME is sniffed after upload."""
    if request.media_type == "image":
        allowed = settings.media_allowed_image_mime_types
        max_bytes = settings.media_max_image_bytes
    else:
        allowed = settings.media_allowed_video_mime_types
        max_bytes = settings.media_max_video_bytes

    if request.mime_type not in allowed:
        raise AppError(
            "MEDIA_TYPE_UNSUPPORTED",
            f"{request.mime_type} is not an accepted {request.media_type} type.",
            status_code=415,
            details={"allowed_mime_types": list(allowed)},
        )
    if request.byte_size > max_bytes:
        raise AppError(
            "MEDIA_TOO_LARGE",
            "Declared upload size exceeds the limit for this media type.",
            status_code=413,
            details={"max_byte_size": max_bytes},
        )
    if request.caption is not None and len(request.caption) > settings.media_caption_max_length:
        raise AppError(
            "CAPTION_TOO_LONG",
            f"Caption exceeds {settings.media_caption_max_length} characters.",
            status_code=400,
            details={"max_length": settings.media_caption_max_length},
        )
    if len(request.vibe_tags) > settings.media_max_vibe_tags:
        raise AppError(
            "TOO_MANY_VIBE_TAGS",
            f"At most {settings.media_max_vibe_tags} vibe tags are allowed.",
            status_code=400,
            details={"max_tags": settings.media_max_vibe_tags},
        )
    for tag in request.vibe_tags:
        if len(tag) > settings.media_vibe_tag_max_length:
            raise AppError(
                "VIBE_TAG_TOO_LONG",
                f"Vibe tags are limited to {settings.media_vibe_tag_max_length} characters.",
                status_code=400,
                details={"tag": tag},
            )


class MediaRateLimiter:
    """Hourly upload and report budgets.

    Unlike location ingest, these fail **closed**: posting already requires a
    live Valkey lease, so an outage cannot be an excuse to accept unbounded
    uploads into the quarantine bucket.
    """

    def __init__(self, redis: Redis[str], settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    @staticmethod
    def _window(now: datetime) -> int:
        return int(now.timestamp()) // HOUR_SECONDS

    async def _incr(self, key: str) -> int:
        pipe = self._redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, HOUR_SECONDS * 2)
        results = await pipe.execute()
        return int(results[0])

    async def _consume(self, buckets: tuple[tuple[str, int, str], ...], now: datetime) -> None:
        retry_after = HOUR_SECONDS - int(now.timestamp()) % HOUR_SECONDS
        for key, limit, scope in buckets:
            try:
                count = await self._incr(key)
            except RedisError as exc:
                logger.error("media_rate_limit_unavailable", scope=scope)
                raise AppError(
                    "MEDIA_RATE_LIMIT_UNAVAILABLE",
                    "Rate limiting is unavailable; try again shortly.",
                    status_code=503,
                ) from exc
            if count > limit:
                raise AppError(
                    "MEDIA_RATE_LIMITED",
                    "Too many uploads. Try again later.",
                    status_code=429,
                    details={"scope": scope, "retry_after_seconds": retry_after},
                )

    async def check_upload(self, *, user_id: UUID, venue_id: UUID, now: datetime) -> None:
        window = self._window(now)
        await self._consume(
            (
                (
                    f"rate:user:{user_id}:media_upload:{window}",
                    self._settings.media_upload_rate_limit_per_user_per_hour,
                    "user",
                ),
                (
                    f"rate:user:{user_id}:venue:{venue_id}:media_upload:{window}",
                    self._settings.media_upload_rate_limit_per_user_per_venue_per_hour,
                    "user_venue",
                ),
            ),
            now,
        )

    async def check_report(self, *, user_id: UUID, now: datetime) -> None:
        window = self._window(now)
        await self._consume(
            (
                (
                    f"rate:user:{user_id}:vibe_report:{window}",
                    self._settings.vibe_report_rate_limit_per_user_per_hour,
                    "user",
                ),
            ),
            now,
        )


class MediaPostingAuthorizer:
    def __init__(self, session: AsyncSession, redis: Redis[str], settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._presence = PresenceService(session, redis, settings)
        self._limits = MediaRateLimiter(redis, settings)

    async def authorize_upload(
        self,
        *,
        user: User,
        request: CreateUploadRequest,
        now: datetime,
    ) -> UploadAuthorization:
        require_media_posting_enabled(self._settings)
        validate_declared_media(request, self._settings)
        if user.onboarding_state == "age_ineligible":
            raise AppError(
                "AGE_INELIGIBLE",
                "This account does not meet the minimum age requirement.",
                status_code=403,
            )
        if user.onboarding_state != "completed":
            raise AppError(
                "ONBOARDING_INCOMPLETE",
                "Finish onboarding before posting Live Vibes.",
                status_code=403,
            )

        device = await self._presence.load_owned_device(user, request.device_id)
        decision = await self._presence.can_post_live_vibe(user, request.venue_id, device, now=now)
        if not decision.allowed or decision.check_in_id is None or decision.venue_id is None:
            reason = decision.reason or "presence_refresh_required"
            raise AppError(
                "MEDIA_POSTING_NOT_AUTHORIZED",
                "A verified check-in at this venue is required to post a Live Vibe.",
                status_code=403,
                details={"reason": reason, "retryable": reason in RETRYABLE_PRESENCE_REASONS},
            )

        await self._assert_pending_intent_budget(user_id=user.id, now=now)
        await self._limits.check_upload(user_id=user.id, venue_id=request.venue_id, now=now)

        assert decision.attribution_mode is not None
        return UploadAuthorization(
            device=device,
            venue_id=decision.venue_id,
            check_in_id=decision.check_in_id,
            attribution_mode=decision.attribution_mode,
        )

    async def _assert_pending_intent_budget(self, *, user_id: UUID, now: datetime) -> None:
        """Cap live presigned intents so a client cannot hoard upload URLs."""
        result = await self._session.execute(
            select(func.count())
            .select_from(MediaAsset)
            .where(
                MediaAsset.owner_user_id == user_id,
                MediaAsset.lifecycle_status == "intent_pending",
                MediaAsset.intent_expires_at > now,
            )
        )
        pending = int(result.scalar_one())
        if pending >= self._settings.media_pending_intent_limit_per_user:
            raise AppError(
                "MEDIA_PENDING_UPLOAD_LIMIT",
                "Finish or abandon your pending uploads before starting another.",
                status_code=429,
                details={"pending": pending},
            )

    async def check_report_rate(self, *, user_id: UUID, now: datetime) -> None:
        await self._limits.check_report(user_id=user_id, now=now)
