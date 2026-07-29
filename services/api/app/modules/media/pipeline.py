"""Validation, sanitising, and moderation of an accepted upload.

Shared by the worker and the tests so there is exactly one description of what
"processed" means.

Two invariants drive the shape of this module:

* **Nothing is published on an unclear answer.** A malware scanner that cannot
  run, a provider that raises, a container we cannot identify — all of them keep
  the Live Vibe unpublished. Publication requires an explicit approval.
* **Long work does not hold a row lock.** Each phase takes a short transaction to
  advance the state machine, releases it, does the slow part against a private
  temp directory, then takes another short transaction to record the result. The
  job lease is what prevents a second worker joining in.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import (
    LiveVibe,
    MediaAsset,
    MediaDerivative,
    ModerationCase,
    ModerationSignal,
    OutboxEvent,
    Venue,
)
from app.modules.media.jobs import ClaimedJob, MediaJobStore
from app.modules.media.lifecycle import MediaLifecycleService, VibeLifecycleService
from app.modules.media.malware import MalwareScanner, build_malware_scanner
from app.modules.media.moderation import (
    ModerationAsset,
    ModerationProvider,
    ModerationResult,
    ModerationSignalResult,
    build_moderation_provider,
)
from app.modules.media.processors import (
    DerivativeOutput,
    ImagePipeline,
    MediaProcessingError,
    MediaValidationError,
    ProcessedMedia,
)
from app.modules.media.storage import (
    ObjectStorage,
    build_object_storage,
    derivative_object_key,
)
from app.modules.media.transcode import VideoTranscoder, build_video_transcoder

logger = get_logger(__name__)

OutcomeStatus = Literal["completed", "invalid", "quarantined", "rejected", "retry", "skipped"]

TEMP_PREFIX = "societe-media-"


@dataclass(frozen=True)
class PipelineOutcome:
    status: OutcomeStatus
    detail: str | None = None

    @property
    def should_retry(self) -> bool:
        return self.status == "retry"


class MediaPipeline:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        storage: ObjectStorage | None = None,
        scanner: MalwareScanner | None = None,
        moderator: ModerationProvider | None = None,
        transcoder: VideoTranscoder | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._storage = storage or build_object_storage(settings)
        self._scanner = scanner or build_malware_scanner(settings)
        self._moderator = moderator or build_moderation_provider(settings)
        self._images = ImagePipeline(settings)
        self._videos = transcoder or build_video_transcoder(settings)
        self._media = MediaLifecycleService()
        self._vibes = VibeLifecycleService(settings)
        self._jobs = MediaJobStore(session, settings)

    async def run(self, job: ClaimedJob, *, now: datetime) -> PipelineOutcome:
        if job.job_type == "validate_process":
            return await self.validate_and_process(job.media_asset_id, now=now)
        if job.job_type == "moderate":
            return await self.moderate(job.media_asset_id, now=now)
        return PipelineOutcome(status="skipped", detail=f"unknown_job_type:{job.job_type}")

    # --------------------------------------------------------- validate/process

    async def validate_and_process(self, media_asset_id: UUID, *, now: datetime) -> PipelineOutcome:
        asset = await self._lock_asset(media_asset_id)
        if asset is None:
            return PipelineOutcome(status="skipped", detail="asset_missing")
        if asset.lifecycle_status not in {"uploaded", "processing_failed"}:
            # Read before the rollback: it expires the instance, and refreshing
            # an attribute afterwards would be a lazy load on an async session.
            observed = asset.lifecycle_status
            await self._session.rollback()
            return PipelineOutcome(status="skipped", detail=observed)

        retry = asset.lifecycle_status == "processing_failed"
        if retry:
            # A new generation keeps object keys unique and leaves any URL a
            # client is still holding pointing at bytes that still exist.
            asset.generation += 1
            await self._retire_derivatives(asset)
        self._media.start_validation(asset, now=now)
        quarantine_key = asset.quarantine_object_key
        media_type = asset.media_type
        declared_byte_size = asset.declared_byte_size
        generation = asset.generation
        await self._session.commit()

        with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as raw_dir:
            workdir = Path(raw_dir)
            original = workdir / "original"
            output_dir = workdir / "out"
            output_dir.mkdir()

            try:
                await self._storage.download_to_path(
                    bucket=self._settings.media_quarantine_bucket,
                    key=quarantine_key,
                    destination=original,
                )
            except Exception as exc:
                logger.warning(
                    "media_original_download_failed",
                    media_asset_id=str(media_asset_id),
                    error=str(exc),
                )
                return await self._fail_processing(media_asset_id, now=now, category="download")

            observed_bytes = original.stat().st_size
            if observed_bytes != declared_byte_size:
                return await self._invalidate(media_asset_id, now=now, reason="byte_size_mismatch")

            scan = await self._scanner.scan(original)
            if scan.verdict == "infected":
                return await self._quarantine(
                    media_asset_id,
                    now=now,
                    summary={
                        "malware_provider": scan.provider,
                        "malware_signature": scan.signature,
                    },
                    reject_vibe=True,
                )
            if scan.verdict != "clean":
                # Unknown is not clean. Hold it for a human.
                return await self._quarantine(
                    media_asset_id,
                    now=now,
                    summary={
                        "malware_provider": scan.provider,
                        "malware_verdict": scan.verdict,
                    },
                    reject_vibe=False,
                )

            await self._advance_to_processing(media_asset_id, now=now)

            try:
                if media_type == "image":
                    processed = self._images.process(original, output_dir)
                else:
                    processed = await self._videos.process(original, output_dir)
            except MediaValidationError as exc:
                return await self._invalidate(media_asset_id, now=now, reason=exc.reason)
            except MediaProcessingError as exc:
                return await self._fail_processing(media_asset_id, now=now, category=exc.category)

            allowed = (
                self._settings.media_allowed_image_mime_types
                if media_type == "image"
                else self._settings.media_allowed_video_mime_types
            )
            if processed.detected_mime_type not in allowed:
                return await self._invalidate(
                    media_asset_id, now=now, reason="detected_mime_not_allowed"
                )

            try:
                stored = await self._upload_derivatives(
                    media_asset_id, generation=generation, processed=processed
                )
            except Exception as exc:
                logger.warning(
                    "media_derivative_upload_failed",
                    media_asset_id=str(media_asset_id),
                    error=str(exc),
                )
                return await self._fail_processing(
                    media_asset_id, now=now, category="derivative_upload"
                )

            return await self._record_processed(
                media_asset_id,
                now=now,
                processed=processed,
                stored=stored,
                generation=generation,
            )

    async def _upload_derivatives(
        self, media_asset_id: UUID, *, generation: int, processed: ProcessedMedia
    ) -> list[tuple[DerivativeOutput, str]]:
        """Upload or reuse generation-aware keys. Replay must not fork objects."""
        stored: list[tuple[DerivativeOutput, str]] = []
        for derivative in processed.derivatives:
            key = derivative_object_key(
                asset_id=media_asset_id,
                generation=generation,
                variant_type=derivative.variant_type,
                mime_type=derivative.mime_type,
            )
            existing = await self._existing_derivative(
                media_asset_id, derivative.variant_type, generation
            )
            if (
                existing is not None
                and existing.status == "ready"
                and existing.checksum_sha256 == derivative.checksum_sha256
                and existing.object_key == key
            ):
                # Safe replay: bytes already match what this run would write.
                stored.append((derivative, key))
                continue
            await self._storage.upload_path(
                bucket=self._settings.media_processed_bucket,
                key=key,
                source=derivative.path,
                content_type=derivative.mime_type,
            )
            stored.append((derivative, key))
        return stored

    async def _existing_derivative(
        self, media_asset_id: UUID, variant_type: str, generation: int
    ) -> MediaDerivative | None:
        result = await self._session.execute(
            select(MediaDerivative).where(
                MediaDerivative.media_asset_id == media_asset_id,
                MediaDerivative.variant_type == variant_type,
                MediaDerivative.generation == generation,
            )
        )
        return result.scalar_one_or_none()

    async def _record_processed(
        self,
        media_asset_id: UUID,
        *,
        now: datetime,
        processed: ProcessedMedia,
        stored: list[tuple[DerivativeOutput, str]],
        generation: int,
    ) -> PipelineOutcome:
        asset = await self._lock_asset(media_asset_id)
        if asset is None:
            return PipelineOutcome(status="skipped", detail="asset_missing")
        self._media.record_probe(
            asset,
            detected_mime_type=processed.detected_mime_type,
            byte_size=processed.byte_size,
            checksum_sha256=processed.checksum_sha256,
            width=processed.width,
            height=processed.height,
            duration_ms=processed.duration_ms,
        )
        for derivative, key in stored:
            existing = await self._existing_derivative(
                asset.id, derivative.variant_type, generation
            )
            if existing is not None:
                # Upsert in place — uniqueness is (asset, variant, generation).
                existing.storage_provider = "minio"
                existing.object_key = key
                existing.mime_type = derivative.mime_type
                existing.byte_size = derivative.byte_size
                existing.width = derivative.width
                existing.height = derivative.height
                existing.duration_ms = derivative.duration_ms
                existing.codec = derivative.codec
                existing.checksum_sha256 = derivative.checksum_sha256
                existing.status = "ready"
            else:
                self._session.add(
                    MediaDerivative(
                        media_asset_id=asset.id,
                        variant_type=derivative.variant_type,
                        storage_provider="minio",
                        object_key=key,
                        mime_type=derivative.mime_type,
                        byte_size=derivative.byte_size,
                        width=derivative.width,
                        height=derivative.height,
                        duration_ms=derivative.duration_ms,
                        codec=derivative.codec,
                        checksum_sha256=derivative.checksum_sha256,
                        generation=generation,
                        status="ready",
                        created_at=now,
                    )
                )
        self._media.await_moderation(asset, now=now)
        await self._jobs.enqueue(asset.id, "moderate", now=now)
        await self._session.commit()
        logger.info(
            "media_processed",
            media_asset_id=str(media_asset_id),
            derivatives=len(stored),
            generation=generation,
        )
        return PipelineOutcome(status="completed", detail="moderation_pending")

    # ---------------------------------------------------------------- moderate

    async def moderate(self, media_asset_id: UUID, *, now: datetime) -> PipelineOutcome:
        asset = await self._lock_asset(media_asset_id)
        if asset is None:
            return PipelineOutcome(status="skipped", detail="asset_missing")
        if asset.lifecycle_status != "moderation_pending":
            observed = asset.lifecycle_status
            await self._session.rollback()
            return PipelineOutcome(status="skipped", detail=observed)

        caption = asset.caption
        tags = list(asset.vibe_tags or [])
        media_type = asset.media_type
        generation = asset.generation
        await self._session.commit()

        reviewable = await self._reviewable_derivatives(media_asset_id, generation)
        with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as raw_dir:
            workdir = Path(raw_dir)
            paths: list[Path] = []
            checksums: list[str] = []
            for derivative in reviewable:
                destination = workdir / f"{derivative.variant_type}"
                try:
                    await self._storage.download_to_path(
                        bucket=self._settings.media_processed_bucket,
                        key=derivative.object_key,
                        destination=destination,
                    )
                except Exception as exc:
                    logger.warning(
                        "moderation_derivative_download_failed",
                        media_asset_id=str(media_asset_id),
                        error=str(exc),
                    )
                    return await self._fail_processing(
                        media_asset_id, now=now, category="moderation_download"
                    )
                paths.append(destination)
                checksums.append(derivative.checksum_sha256)

            # Only sanitised derivatives are handed to the provider. The raw
            # original never leaves quarantine.
            request = ModerationAsset(
                media_asset_id=media_asset_id,
                media_type=media_type,
                caption=caption,
                vibe_tags=tags,
                derivative_paths=paths,
                derivative_checksums=checksums,
            )
            try:
                result = await self._moderator.moderate(request)
            except Exception as exc:
                logger.error(
                    "moderation_provider_failed",
                    media_asset_id=str(media_asset_id),
                    error=str(exc),
                )
                result = ModerationResult(
                    decision="manual_review",
                    provider=getattr(self._moderator, "provider", "unknown"),
                    policy_version=self._settings.media_moderation_policy_version,
                    signals=[
                        ModerationSignalResult(
                            category="provider_error",
                            confidence=None,
                        )
                    ],
                )

        return await self._apply_moderation(media_asset_id, result=result, now=now)

    async def _apply_moderation(
        self, media_asset_id: UUID, *, result: ModerationResult, now: datetime
    ) -> PipelineOutcome:
        asset = await self._lock_asset(media_asset_id)
        if asset is None:
            return PipelineOutcome(status="skipped", detail="asset_missing")
        vibe = await self._load_vibe(asset.id)

        case = ModerationCase(
            media_asset_id=asset.id,
            subject_user_id=asset.owner_user_id,
            status=result.case_status,
            policy_version=result.policy_version,
            final_action=result.decision,
            created_at=now,
            resolved_at=None if result.decision == "manual_review" else now,
        )
        self._session.add(case)
        await self._session.flush()
        for signal in result.signals:
            self._session.add(
                ModerationSignal(
                    moderation_case_id=case.id,
                    provider=result.provider,
                    model_version=signal.model_version,
                    category=signal.category,
                    confidence=signal.confidence,
                    raw_reference=signal.raw_reference,
                    created_at=now,
                )
            )

        summary: dict[str, Any] = {
            "moderation_provider": result.provider,
            "moderation_policy_version": result.policy_version,
            "moderation_categories": [signal.category for signal in result.signals],
        }

        if result.decision == "approved":
            self._media.mark_ready(asset, now=now, summary=summary)
            outcome = PipelineOutcome(status="completed", detail="published")
            if vibe is not None:
                timezone_name = await self._venue_timezone(asset.venue_id)
                expires_at = self._vibes.publish(vibe, now=now, venue_timezone=timezone_name)
                self._session.add(
                    OutboxEvent(
                        aggregate_type="live_vibe",
                        aggregate_id=vibe.id,
                        event_type="live_vibe.published",
                        payload={
                            "live_vibe_id": str(vibe.id),
                            "venue_id": str(vibe.venue_id),
                            "media_asset_id": str(asset.id),
                            "attribution_mode": vibe.attribution_mode,
                            "published_at": now.isoformat(),
                            "expires_at": expires_at.isoformat(),
                        },
                        occurred_at=now,
                        available_at=now,
                    )
                )
            else:
                from app.modules.stories.publication import publish_content_for_media_asset

                handled = await publish_content_for_media_asset(
                    self._session, asset.id, now=now, settings=self._settings
                )
                outcome = PipelineOutcome(
                    status="completed",
                    detail="published" if handled else "approved_without_vibe",
                )
        elif result.decision == "rejected":
            self._media.mark_rejected(asset, now=now, summary=summary)
            if vibe is not None:
                self._vibes.reject(vibe, now=now, reason="moderation_rejected")
            else:
                from app.modules.stories.publication import reject_content_for_media_asset

                await reject_content_for_media_asset(self._session, asset.id, now=now)
            outcome = PipelineOutcome(status="rejected", detail="moderation_rejected")
        else:
            self._media.mark_manual_review(asset, now=now, summary=summary)
            # The vibe stays unpublished while a human decides.
            outcome = PipelineOutcome(status="quarantined", detail="manual_review")

        await self._session.commit()
        logger.info(
            "media_moderated",
            media_asset_id=str(media_asset_id),
            decision=result.decision,
            provider=result.provider,
        )
        return outcome

    # ----------------------------------------------------------------- helpers

    async def _lock_asset(self, media_asset_id: UUID) -> MediaAsset | None:
        result = await self._session.execute(
            select(MediaAsset).where(MediaAsset.id == media_asset_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def _load_vibe(self, media_asset_id: UUID) -> LiveVibe | None:
        result = await self._session.execute(
            select(LiveVibe).where(LiveVibe.media_asset_id == media_asset_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def _venue_timezone(self, venue_id: UUID) -> str:
        result = await self._session.execute(select(Venue.timezone).where(Venue.id == venue_id))
        timezone_name = result.scalar_one_or_none()
        return timezone_name or self._settings.default_purge_timezone

    async def _reviewable_derivatives(
        self, media_asset_id: UUID, generation: int
    ) -> list[MediaDerivative]:
        result = await self._session.execute(
            select(MediaDerivative).where(
                MediaDerivative.media_asset_id == media_asset_id,
                MediaDerivative.generation == generation,
                MediaDerivative.status == "ready",
            )
        )
        derivatives = list(result.scalars().all())
        preferred = ("image_1080", "video_poster", "thumbnail")
        images = [d for d in derivatives if d.mime_type.startswith("image/")]
        return sorted(
            images,
            key=lambda d: (
                preferred.index(d.variant_type) if d.variant_type in preferred else len(preferred)
            ),
        )

    async def _retire_derivatives(self, asset: MediaAsset) -> None:
        result = await self._session.execute(
            select(MediaDerivative).where(
                MediaDerivative.media_asset_id == asset.id,
                MediaDerivative.status == "ready",
            )
        )
        for derivative in result.scalars().all():
            derivative.status = "deleted"

    async def _advance_to_processing(self, media_asset_id: UUID, *, now: datetime) -> None:
        asset = await self._lock_asset(media_asset_id)
        if asset is None:
            return
        self._media.start_processing(asset, now=now)
        await self._session.commit()

    async def _invalidate(
        self, media_asset_id: UUID, *, now: datetime, reason: str
    ) -> PipelineOutcome:
        asset = await self._lock_asset(media_asset_id)
        if asset is None:
            return PipelineOutcome(status="skipped", detail="asset_missing")
        self._media.mark_invalid(asset, now=now, reason=reason)
        vibe = await self._load_vibe(asset.id)
        if vibe is not None:
            self._vibes.reject(vibe, now=now, reason=f"media_invalid:{reason}")
        await self._session.commit()
        logger.info("media_invalid", media_asset_id=str(media_asset_id), reason=reason)
        return PipelineOutcome(status="invalid", detail=reason)

    async def _quarantine(
        self,
        media_asset_id: UUID,
        *,
        now: datetime,
        summary: dict[str, Any],
        reject_vibe: bool,
    ) -> PipelineOutcome:
        asset = await self._lock_asset(media_asset_id)
        if asset is None:
            return PipelineOutcome(status="skipped", detail="asset_missing")
        self._media.mark_quarantined(asset, now=now, summary=summary)
        vibe = await self._load_vibe(asset.id)
        if vibe is not None and reject_vibe:
            self._vibes.reject(vibe, now=now, reason="malware_detected")
        await self._session.commit()
        logger.warning("media_quarantined", media_asset_id=str(media_asset_id), **summary)
        return PipelineOutcome(status="quarantined", detail="quarantined")

    async def _fail_processing(
        self, media_asset_id: UUID, *, now: datetime, category: str
    ) -> PipelineOutcome:
        asset = await self._lock_asset(media_asset_id)
        if asset is None:
            return PipelineOutcome(status="skipped", detail="asset_missing")
        self._media.mark_processing_failed(asset, now=now, error_category=category)
        await self._session.commit()
        return PipelineOutcome(status="retry", detail=category)
