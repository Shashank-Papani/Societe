"""Upload intent and completion.

The flow is two calls with a client-side PUT in between:

1. ``create_upload`` authorizes, mints a server-generated quarantine key, and
   returns one presigned PUT. A ``media_assets`` row and its draft ``live_vibes``
   row are created in the same transaction so an orphan asset with no post — or a
   post with no asset — is not representable.
2. ``complete_upload`` re-runs every check. Authorization at step 1 is not
   evidence of authorization at step 2: minutes may have passed, the lease may
   have moved venues, the device may have been revoked. The object's size must
   match the declared size exactly, and the job row is inserted in the same
   transaction that marks the asset ``uploaded`` so an accepted upload can never
   sit unqueued.

After an accepted completion the pipeline is independent of presence. The user
may walk out; the media is already admitted and continues to processing.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import (
    LiveVibe,
    MediaAsset,
    MediaDerivative,
    MediaProcessingJob,
    OutboxEvent,
    User,
)
from app.modules.media.access import may_issue_signed_urls
from app.modules.media.authz import MediaPostingAuthorizer
from app.modules.media.lifecycle import MediaLifecycleService, VibeLifecycleService
from app.modules.media.schemas import (
    CompleteUploadRequest,
    CreateUploadRequest,
    CreateUploadResponse,
    UploadInstruction,
    UploadStatusResponse,
)
from app.modules.media.storage import ObjectStorage, build_object_storage, quarantine_object_key
from app.modules.media.urls import build_signed_variants
from app.modules.presence.service import PresenceService

logger = get_logger(__name__)

FAILURE_STATUSES = frozenset(
    {"invalid", "processing_failed", "rejected", "upload_expired", "revoked"}
)


class MediaService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis[str],
        settings: Settings,
        storage: ObjectStorage | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._storage = storage or build_object_storage(settings)
        self._authorizer = MediaPostingAuthorizer(session, redis, settings)
        self._presence = PresenceService(session, redis, settings)
        self._media_lifecycle = MediaLifecycleService()
        self._vibe_lifecycle = VibeLifecycleService(settings)

    # ------------------------------------------------------------------ create

    async def create_upload(
        self, *, user: User, request: CreateUploadRequest, now: datetime
    ) -> CreateUploadResponse:
        authorization = await self._authorizer.authorize_upload(user=user, request=request, now=now)

        asset_id = uuid4()
        object_key = quarantine_object_key(
            owner_user_id=user.id, asset_id=asset_id, mime_type=request.mime_type
        )
        intent_expires_at = now + timedelta(seconds=self._settings.media_upload_intent_ttl_seconds)

        asset = MediaAsset(
            id=asset_id,
            owner_user_id=user.id,
            venue_id=authorization.venue_id,
            author_check_in_id=authorization.check_in_id,
            device_id=authorization.device.id,
            media_type=request.media_type,
            lifecycle_status="intent_pending",
            moderation_status="pending",
            attribution_mode=authorization.attribution_mode,
            quarantine_object_key=object_key,
            declared_mime_type=request.mime_type,
            declared_byte_size=request.byte_size,
            original_filename=request.original_filename,
            caption=request.caption,
            vibe_tags=list(request.vibe_tags),
            intent_expires_at=intent_expires_at,
            generation=1,
            moderation_summary=(
                {"declared_checksum_sha256": request.checksum_sha256}
                if request.checksum_sha256
                else {}
            ),
            created_at=now,
        )
        vibe = LiveVibe(
            id=uuid4(),
            venue_id=authorization.venue_id,
            author_user_id=user.id,
            media_asset_id=asset_id,
            author_check_in_id=authorization.check_in_id,
            caption=request.caption,
            vibe_tags=list(request.vibe_tags),
            attribution_mode=authorization.attribution_mode,
            publication_status="draft",
            created_at=now,
        )
        self._session.add(asset)
        await self._session.flush()
        self._session.add(vibe)
        await self._session.commit()

        upload = await self._storage.presign_put(
            bucket=self._settings.media_quarantine_bucket,
            key=object_key,
            content_type=request.mime_type,
            expires_in=self._settings.media_presigned_put_ttl_seconds,
        )
        logger.info(
            "media_upload_intent_created",
            media_asset_id=str(asset_id),
            venue_id=str(authorization.venue_id),
            media_type=request.media_type,
            attribution_mode=authorization.attribution_mode,
        )
        return CreateUploadResponse(
            upload_id=asset_id,
            live_vibe_id=vibe.id,
            lifecycle_status="intent_pending",
            attribution_mode=authorization.attribution_mode,  # type: ignore[arg-type]
            intent_expires_at=intent_expires_at,
            max_byte_size=request.byte_size,
            upload=UploadInstruction(
                method="PUT",
                url=upload.url,
                headers=upload.headers,
                expires_at=min(upload.expires_at, intent_expires_at),
            ),
        )

    # ---------------------------------------------------------------- complete

    async def complete_upload(
        self,
        *,
        user: User,
        upload_id: UUID,
        request: CompleteUploadRequest,
        now: datetime,
    ) -> UploadStatusResponse:
        asset = await self._load_owned_asset(user, upload_id, for_update=True)
        vibe = await self._load_vibe(asset.id)

        if request.device_id != asset.device_id:
            raise AppError(
                "MEDIA_DEVICE_MISMATCH",
                "Complete the upload from the device that created it.",
                status_code=403,
            )
        device = await self._presence.load_owned_device(user, request.device_id)

        if asset.intent_consumed_at is not None or asset.lifecycle_status != "intent_pending":
            # Already accepted (or already failed). Report state instead of
            # re-admitting bytes that are past the admission gate.
            if asset.lifecycle_status == "intent_pending":
                raise AppError(
                    "MEDIA_UPLOAD_ALREADY_COMPLETED",
                    "This upload was already completed.",
                    status_code=409,
                )
            if asset.lifecycle_status == "upload_expired":
                raise AppError(
                    "MEDIA_UPLOAD_INTENT_EXPIRED",
                    "The upload window expired. Start a new upload.",
                    status_code=409,
                )
            return await self.build_status(asset, vibe, now=now)

        if now >= asset.intent_expires_at:
            self._media_lifecycle.mark_intent_expired(asset, now=now)
            if vibe is not None:
                self._vibe_lifecycle.expire(vibe, now=now)
            await self._session.commit()
            raise AppError(
                "MEDIA_UPLOAD_INTENT_EXPIRED",
                "The upload window expired. Start a new upload.",
                status_code=409,
            )

        decision = await self._presence.can_post_live_vibe(user, asset.venue_id, device, now=now)
        if not decision.allowed:
            raise AppError(
                "MEDIA_POSTING_NOT_AUTHORIZED",
                "A verified check-in at this venue is required to finish the upload.",
                status_code=403,
                details={"reason": decision.reason or "presence_refresh_required"},
            )

        stat = await self._storage.stat_object(
            bucket=self._settings.media_quarantine_bucket,
            key=asset.quarantine_object_key,
        )
        if stat is None:
            raise AppError(
                "MEDIA_OBJECT_MISSING",
                "No uploaded object was found for this upload.",
                status_code=409,
            )
        if stat.byte_size != asset.declared_byte_size:
            # An exact match is the cheapest defence against a client that
            # declares a small image and uploads a large payload.
            raise AppError(
                "MEDIA_SIZE_MISMATCH",
                "Uploaded object size does not match the declared size.",
                status_code=409,
                details={
                    "declared_byte_size": asset.declared_byte_size,
                    "observed_byte_size": stat.byte_size,
                },
            )

        if request.checksum_sha256 is not None:
            summary = dict(asset.moderation_summary or {})
            summary["declared_checksum_sha256"] = request.checksum_sha256
            asset.moderation_summary = summary

        self._media_lifecycle.mark_uploaded(asset, now=now)
        if vibe is not None:
            self._vibe_lifecycle.start_processing(vibe)
        self._session.add(
            MediaProcessingJob(
                media_asset_id=asset.id,
                job_type="validate_process",
                status="pending",
                next_attempt_at=now,
                created_at=now,
            )
        )
        self._session.add(
            OutboxEvent(
                aggregate_type="media_asset",
                aggregate_id=asset.id,
                event_type="media.upload_completed",
                payload={
                    "media_asset_id": str(asset.id),
                    "live_vibe_id": str(vibe.id) if vibe is not None else None,
                    "venue_id": str(asset.venue_id),
                    "media_type": asset.media_type,
                    "occurred_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()
        logger.info("media_upload_completed", media_asset_id=str(asset.id))
        return await self.build_status(asset, vibe, now=now)

    # ------------------------------------------------------------------ status

    async def get_upload(
        self, *, user: User, upload_id: UUID, now: datetime
    ) -> UploadStatusResponse:
        asset = await self._load_owned_asset(user, upload_id)
        vibe = await self._load_vibe(asset.id)
        return await self.build_status(asset, vibe, now=now)

    async def build_status(
        self, asset: MediaAsset, vibe: LiveVibe | None, *, now: datetime
    ) -> UploadStatusResponse:
        variants = []
        if may_issue_signed_urls(asset, vibe, now=now, settings=self._settings, creator_view=True):
            result = await self._session.execute(
                select(MediaDerivative).where(
                    MediaDerivative.media_asset_id == asset.id,
                    MediaDerivative.generation == asset.generation,
                    MediaDerivative.status == "ready",
                )
            )
            variants = await build_signed_variants(
                self._storage, self._settings, list(result.scalars().all()), now=now
            )
        summary = asset.moderation_summary or {}
        failure_reason: str | None = None
        if asset.lifecycle_status in FAILURE_STATUSES:
            raw = summary.get("invalid_reason") or summary.get("error_category")
            failure_reason = str(raw) if raw is not None else asset.lifecycle_status
        return UploadStatusResponse(
            upload_id=asset.id,
            media_type=asset.media_type,  # type: ignore[arg-type]
            lifecycle_status=asset.lifecycle_status,  # type: ignore[arg-type]
            moderation_status=asset.moderation_status,  # type: ignore[arg-type]
            attribution_mode=asset.attribution_mode,  # type: ignore[arg-type]
            live_vibe_id=vibe.id if vibe is not None else None,
            publication_status=vibe.publication_status if vibe is not None else None,  # type: ignore[arg-type]
            published_at=vibe.published_at if vibe is not None else None,
            expires_at=vibe.expires_at if vibe is not None else None,
            intent_expires_at=asset.intent_expires_at,
            variants=variants,
            failure_reason=failure_reason,
        )

    # ------------------------------------------------------------------ expiry

    async def expire_abandoned_intents(self, *, now: datetime, limit: int = 200) -> int:
        """Close intents whose window passed without a completion."""
        result = await self._session.execute(
            select(MediaAsset)
            .where(
                MediaAsset.lifecycle_status == "intent_pending",
                MediaAsset.intent_expires_at <= now,
            )
            .order_by(MediaAsset.intent_expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        assets = list(result.scalars().all())
        for asset in assets:
            self._media_lifecycle.mark_intent_expired(asset, now=now)
            vibe = await self._load_vibe(asset.id)
            if vibe is not None:
                self._vibe_lifecycle.expire(vibe, now=now)
        if assets:
            await self._session.commit()
        return len(assets)

    # ------------------------------------------------------------------ shared

    async def _load_owned_asset(
        self, user: User, upload_id: UUID, *, for_update: bool = False
    ) -> MediaAsset:
        stmt = select(MediaAsset).where(MediaAsset.id == upload_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        asset = result.scalar_one_or_none()
        # A foreign upload id is reported as missing, not forbidden: existence is
        # itself information about another account's activity.
        if asset is None or asset.owner_user_id != user.id or asset.lifecycle_status == "deleted":
            raise AppError("MEDIA_UPLOAD_NOT_FOUND", "Upload not found.", status_code=404)
        return asset

    async def _load_vibe(self, media_asset_id: UUID) -> LiveVibe | None:
        result = await self._session.execute(
            select(LiveVibe).where(LiveVibe.media_asset_id == media_asset_id)
        )
        return result.scalar_one_or_none()
