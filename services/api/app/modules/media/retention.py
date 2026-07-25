"""Expiry and retention for media objects and Live Vibes.

Four independent clocks, because the bytes have different reasons to exist:

* an upload that never completed is abandoned litter — 24 h;
* a quarantined original whose derivatives are live is a re-processing safety net
  — 24 h after processing, then it is a liability;
* a rejected original is safety evidence — 3 days;
* processed derivatives outlive public visibility briefly so a client mid-fetch
  does not 404 — 7 days after the public window closed.

Deleting the database row before the object leaks storage silently, so every
method deletes the object first and only then records the purge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import LiveVibe, MediaAsset, MediaDerivative, OutboxEvent
from app.modules.media.lifecycle import MediaLifecycleService, VibeLifecycleService
from app.modules.media.storage import ObjectStorage, build_object_storage

logger = get_logger(__name__)

#: Assets whose original is still worth keeping around for re-processing.
DERIVATIVE_BEARING_STATUSES = frozenset({"ready", "manual_review"})


@dataclass(frozen=True)
class RetentionResult:
    expired_vibes: int = 0
    expired_intents: int = 0
    incomplete_uploads_purged: int = 0
    processed_originals_purged: int = 0
    rejected_originals_purged: int = 0
    derivative_sets_purged: int = 0

    @property
    def total(self) -> int:
        return (
            self.expired_vibes
            + self.expired_intents
            + self.incomplete_uploads_purged
            + self.processed_originals_purged
            + self.rejected_originals_purged
            + self.derivative_sets_purged
        )


class MediaRetentionService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        storage: ObjectStorage | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._storage = storage or build_object_storage(settings)
        self._media = MediaLifecycleService()
        self._vibes = VibeLifecycleService(settings)

    # ------------------------------------------------------------------ expiry

    async def expire_due_vibes(self, *, now: datetime, limit: int = 200) -> int:
        """Published vibes past their window stop being public immediately."""
        result = await self._session.execute(
            select(LiveVibe)
            .where(
                LiveVibe.publication_status.in_(("published", "hidden")),
                LiveVibe.expires_at.is_not(None),
                LiveVibe.expires_at <= now,
            )
            .order_by(LiveVibe.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        vibes = list(result.scalars().all())
        for vibe in vibes:
            self._vibes.expire(vibe, now=now)
            self._session.add(
                OutboxEvent(
                    aggregate_type="live_vibe",
                    aggregate_id=vibe.id,
                    event_type="live_vibe.expired",
                    payload={
                        "live_vibe_id": str(vibe.id),
                        "venue_id": str(vibe.venue_id),
                        "media_asset_id": str(vibe.media_asset_id),
                        "expired_at": now.isoformat(),
                    },
                    occurred_at=now,
                    available_at=now,
                )
            )
        if vibes:
            await self._session.commit()
        return len(vibes)

    # --------------------------------------------------------------- retention

    async def purge_incomplete_uploads(self, *, now: datetime, limit: int = 200) -> int:
        cutoff = now - timedelta(hours=self._settings.retention_incomplete_upload_hours)
        assets = await self._select_assets(
            MediaAsset.lifecycle_status.in_(("intent_pending", "upload_expired")),
            MediaAsset.intent_expires_at <= cutoff,
            limit=limit,
        )
        purged = 0
        for asset in assets:
            await self._delete_quarantine_original(asset)
            self._media.record_original_purged(asset, now=now)
            if asset.lifecycle_status == "intent_pending":
                self._media.mark_intent_expired(asset, now=now)
            self._media.mark_deleted(asset, now=now, reason="retention_incomplete_upload")
            await self._delete_vibe(asset, now=now, reason="retention_incomplete_upload")
            purged += 1
        if purged:
            await self._session.commit()
        return purged

    async def purge_processed_originals(self, *, now: datetime, limit: int = 200) -> int:
        """Drop the quarantined original once derivatives have been serving."""
        cutoff = now - timedelta(hours=self._settings.retention_processed_original_hours)
        assets = await self._select_assets(
            MediaAsset.lifecycle_status.in_(tuple(DERIVATIVE_BEARING_STATUSES)),
            MediaAsset.processed_at.is_not(None),
            MediaAsset.processed_at <= cutoff,
            limit=limit,
        )
        purged = 0
        for asset in assets:
            if _original_already_purged(asset):
                continue
            await self._delete_quarantine_original(asset)
            self._media.record_original_purged(asset, now=now)
            purged += 1
        if purged:
            await self._session.commit()
        return purged

    async def purge_rejected_originals(self, *, now: datetime, limit: int = 200) -> int:
        """Rejections keep their original briefly as safety/appeal evidence."""
        cutoff = now - timedelta(days=self._settings.retention_rejected_original_days)
        assets = await self._select_assets(
            MediaAsset.lifecycle_status.in_(("rejected", "invalid", "revoked")),
            MediaAsset.created_at <= cutoff,
            limit=limit,
        )
        purged = 0
        for asset in assets:
            if _original_already_purged(asset):
                continue
            await self._delete_quarantine_original(asset)
            self._media.record_original_purged(asset, now=now)
            purged += 1
        if purged:
            await self._session.commit()
        return purged

    async def purge_expired_derivatives(self, *, now: datetime, limit: int = 100) -> int:
        """Delete processed output a while after the public window closed."""
        cutoff = now - timedelta(days=self._settings.retention_processed_derivative_days)
        result = await self._session.execute(
            select(LiveVibe)
            .where(
                LiveVibe.publication_status.in_(("expired", "removed", "rejected", "revoked")),
                LiveVibe.expires_at.is_not(None),
                LiveVibe.expires_at <= cutoff,
            )
            .order_by(LiveVibe.expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        vibes = list(result.scalars().all())
        purged = 0
        for vibe in vibes:
            derivatives = await self._live_derivatives(vibe.media_asset_id)
            if not derivatives:
                continue
            for derivative in derivatives:
                await self._storage.delete_object(
                    bucket=self._settings.media_processed_bucket,
                    key=derivative.object_key,
                )
                derivative.status = "deleted"
            purged += 1
        if purged:
            await self._session.commit()
        return purged

    async def run_all(self, *, now: datetime) -> RetentionResult:
        return RetentionResult(
            expired_vibes=await self.expire_due_vibes(now=now),
            incomplete_uploads_purged=await self.purge_incomplete_uploads(now=now),
            processed_originals_purged=await self.purge_processed_originals(now=now),
            rejected_originals_purged=await self.purge_rejected_originals(now=now),
            derivative_sets_purged=await self.purge_expired_derivatives(now=now),
        )

    # ----------------------------------------------------------------- helpers

    async def _select_assets(self, *criteria: Any, limit: int) -> list[MediaAsset]:
        result = await self._session.execute(
            select(MediaAsset)
            .where(*criteria)
            .order_by(MediaAsset.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def _live_derivatives(self, media_asset_id: Any) -> list[MediaDerivative]:
        result = await self._session.execute(
            select(MediaDerivative).where(
                MediaDerivative.media_asset_id == media_asset_id,
                MediaDerivative.status == "ready",
            )
        )
        return list(result.scalars().all())

    async def _delete_quarantine_original(self, asset: MediaAsset) -> None:
        if _original_already_purged(asset):
            return
        await self._storage.delete_object(
            bucket=self._settings.media_quarantine_bucket,
            key=asset.quarantine_object_key,
        )
        logger.info("media_original_purged", media_asset_id=str(asset.id))

    async def _delete_vibe(self, asset: MediaAsset, *, now: datetime, reason: str) -> None:
        result = await self._session.execute(
            select(LiveVibe).where(LiveVibe.media_asset_id == asset.id).with_for_update()
        )
        vibe = result.scalar_one_or_none()
        if vibe is None:
            return
        if vibe.publication_status not in {"deleted"}:
            self._vibes.delete(vibe, now=now, reason=reason)


def _original_already_purged(asset: MediaAsset) -> bool:
    return "original_purged_at" in (asset.moderation_summary or {})
