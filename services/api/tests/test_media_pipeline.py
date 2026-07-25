"""From accepted bytes to a published Live Vibe — and the paths that stop short.

Publication is the only outcome that requires an explicit approval. Everything
else here checks that an unclear answer (malware, an unreadable container, a
provider that raises, a scanner that cannot run) leaves the vibe unpublished.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from media_support import MediaWorld, put_bytes
from societe_media_fixtures import write_jpeg_with_exif_gps, write_png
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.db.models import (
    LiveVibe,
    MediaAsset,
    MediaDerivative,
    ModerationCase,
    ModerationSignal,
    OutboxEvent,
)
from app.modules.media.jobs import MediaJobStore
from app.modules.media.lifecycle import compute_vibe_expiry
from app.modules.media.malware import EICAR_SIGNATURE, FailClosedMalwareScanner
from app.modules.media.moderation import ModerationAsset, ModerationResult
from app.modules.media.pipeline import MediaPipeline
from app.modules.media.retention import MediaRetentionService
from app.modules.media.schemas import CompleteUploadRequest, CreateUploadRequest
from app.modules.media.service import MediaService
from app.modules.media.storage import ObjectStorage
from app.modules.media.urls import build_signed_variants

NOW = datetime.now(UTC)


class ExplodingModerationProvider:
    """A provider having a bad day. Must not become an approval."""

    provider = "exploding"

    async def moderate(self, asset: ModerationAsset) -> ModerationResult:
        raise RuntimeError("provider unavailable")

    async def start_video_moderation(self, asset: ModerationAsset) -> str:
        raise NotImplementedError

    async def get_video_moderation(self, job_id: str) -> ModerationResult:
        raise NotImplementedError


async def accepted_upload(
    world: MediaWorld,
    storage: ObjectStorage,
    payload: bytes,
    *,
    mime_type: str = "image/png",
    media_type: str = "image",
    caption: str | None = "rooftop set",
    vibe_tags: list[str] | None = None,
    now: datetime | None = None,
) -> UUID:
    """Walk an upload all the way to `uploaded`, the pipeline's entry state."""
    moment = now or NOW
    await world.grant_lease()
    media = MediaService(world.session, world.redis, world.settings, storage)
    response = await media.create_upload(
        user=world.author,
        request=CreateUploadRequest.model_validate(
            {
                "venue_id": str(world.venue_id),
                "device_id": str(world.device_id),
                "media_type": media_type,
                "mime_type": mime_type,
                "byte_size": len(payload),
                "caption": caption,
                "vibe_tags": vibe_tags or ["rooftop"],
            }
        ),
        now=moment,
    )
    await put_bytes(response.upload.url, response.upload.headers, payload)
    await media.complete_upload(
        user=world.author,
        upload_id=response.upload_id,
        request=CompleteUploadRequest(device_id=world.device_id),
        now=moment,
    )
    return response.upload_id


def pipeline(world: MediaWorld, storage: ObjectStorage, **kwargs: object) -> MediaPipeline:
    return MediaPipeline(world.session, world.settings, storage=storage, **kwargs)  # type: ignore[arg-type]


async def load_asset(world: MediaWorld, asset_id: UUID) -> MediaAsset:
    await world.session.commit()
    result = await world.session.execute(select(MediaAsset).where(MediaAsset.id == asset_id))
    return result.scalar_one()


async def load_vibe(world: MediaWorld, asset_id: UUID) -> LiveVibe:
    result = await world.session.execute(
        select(LiveVibe).where(LiveVibe.media_asset_id == asset_id)
    )
    return result.scalar_one()


async def load_derivatives(world: MediaWorld, asset_id: UUID) -> list[MediaDerivative]:
    result = await world.session.execute(
        select(MediaDerivative)
        .where(MediaDerivative.media_asset_id == asset_id)
        .order_by(MediaDerivative.variant_type)
    )
    return list(result.scalars().all())


# ------------------------------------------------------------------ happy path


async def test_an_image_is_sanitised_stored_and_published(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_jpeg_with_exif_gps(tmp_path / "post.jpg", width=1600, height=900).read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload, mime_type="image/jpeg")
    runner = pipeline(media_world, object_storage)

    processed = await runner.validate_and_process(asset_id, now=NOW)
    assert processed.status == "completed"
    assert (await load_asset(media_world, asset_id)).lifecycle_status == "moderation_pending"

    published = await runner.moderate(asset_id, now=NOW)
    assert published.status == "completed"

    asset = await load_asset(media_world, asset_id)
    assert asset.lifecycle_status == "ready"
    assert asset.moderation_status == "approved"
    # The checksum is the server's own hash of the bytes it read.
    assert asset.checksum_sha256 is not None
    assert asset.detected_mime_type == "image/jpeg"
    assert asset.byte_size == len(payload)

    vibe = await load_vibe(media_world, asset_id)
    assert vibe.publication_status == "published"
    assert vibe.published_at == NOW
    assert vibe.expires_at == compute_vibe_expiry(NOW, media_world.timezone, media_world.settings)


async def test_derivative_keys_carry_the_asset_and_generation(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "keys.png", width=1400, height=1000).read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    await pipeline(media_world, object_storage).validate_and_process(asset_id, now=NOW)

    derivatives = await load_derivatives(media_world, asset_id)
    assert [d.variant_type for d in derivatives] == ["image_1080", "image_720", "thumbnail"]
    for derivative in derivatives:
        assert derivative.object_key == (f"processed/{asset_id}/g1/{derivative.variant_type}.webp")
        assert derivative.mime_type == "image/webp"
        assert derivative.status == "ready"
        assert derivative.generation == 1
        stat = await object_storage.stat_object(
            bucket=media_world.settings.media_processed_bucket, key=derivative.object_key
        )
        assert stat is not None
        assert stat.byte_size == derivative.byte_size


async def test_a_second_variant_of_the_same_kind_and_generation_is_rejected_by_the_database(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """Uniqueness is (asset, variant_type, generation)."""
    payload = write_png(tmp_path / "dupe.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    await pipeline(media_world, object_storage).validate_and_process(asset_id, now=NOW)
    existing = (await load_derivatives(media_world, asset_id))[0]

    media_world.session.add(
        MediaDerivative(
            media_asset_id=asset_id,
            variant_type=existing.variant_type,
            object_key="processed/collision",
            mime_type="image/webp",
            byte_size=1,
            checksum_sha256="c" * 64,
            generation=existing.generation,
            status="ready",
        )
    )
    with pytest.raises(IntegrityError, match=r"uq|unique|duplicate"):
        await media_world.session.commit()
    await media_world.session.rollback()


async def test_served_urls_are_signed_short_lived_and_key_free(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "signed.png", width=900, height=600).read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    runner = pipeline(media_world, object_storage)
    await runner.validate_and_process(asset_id, now=NOW)
    await runner.moderate(asset_id, now=NOW)

    variants = await build_signed_variants(
        object_storage,
        media_world.settings,
        await load_derivatives(media_world, asset_id),
        now=NOW,
    )
    assert {variant.variant_type for variant in variants} == {
        "image_1080",
        "image_720",
        "thumbnail",
    }
    ttl = media_world.settings.media_signed_url_ttl_seconds
    assert ttl == 300
    for variant in variants:
        assert "X-Amz-Signature=" in variant.url
        assert f"X-Amz-Expires={ttl}" in variant.url
        assert variant.expires_at == NOW + timedelta(seconds=ttl)


async def test_moderation_reads_sanitised_derivatives_not_the_original(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    # Recorded inside the call: the pipeline works in a temp directory it removes
    # as soon as moderation returns.
    seen: list[tuple[str, bytes]] = []

    class RecordingProvider:
        provider = "recording"

        async def moderate(self, asset: ModerationAsset) -> ModerationResult:
            for path in asset.derivative_paths:
                assert path.exists()
                seen.append((path.name, path.read_bytes()[:4]))
            return ModerationResult(
                decision="approved", provider=self.provider, policy_version="test"
            )

        async def start_video_moderation(self, asset: ModerationAsset) -> str:
            raise NotImplementedError

        async def get_video_moderation(self, job_id: str) -> ModerationResult:
            raise NotImplementedError

    payload = write_jpeg_with_exif_gps(tmp_path / "review.jpg").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload, mime_type="image/jpeg")
    runner = pipeline(media_world, object_storage, moderator=RecordingProvider())
    await runner.validate_and_process(asset_id, now=NOW)
    await runner.moderate(asset_id, now=NOW)

    assert seen
    # The most detailed sanitised image comes first, and every reviewed file is a
    # WebP derivative — never the uploaded JPEG.
    assert seen[0][0] == "image_1080"
    assert {magic for _, magic in seen} == {b"RIFF"}


async def test_a_moderation_case_and_its_signals_are_recorded(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "case.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    runner = pipeline(media_world, object_storage)
    await runner.validate_and_process(asset_id, now=NOW)
    await runner.moderate(asset_id, now=NOW)

    case = (
        await media_world.session.execute(
            select(ModerationCase).where(ModerationCase.media_asset_id == asset_id)
        )
    ).scalar_one()
    assert case.status == "auto_approved"
    assert case.final_action == "approved"
    assert case.policy_version == media_world.settings.media_moderation_policy_version

    signals = (
        (
            await media_world.session.execute(
                select(ModerationSignal).where(ModerationSignal.moderation_case_id == case.id)
            )
        )
        .scalars()
        .all()
    )
    assert [signal.category for signal in signals] == ["no_policy_violation"]


async def test_publication_emits_one_event(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "event.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    runner = pipeline(media_world, object_storage)
    await runner.validate_and_process(asset_id, now=NOW)
    await runner.moderate(asset_id, now=NOW)

    vibe = await load_vibe(media_world, asset_id)
    events = (
        (
            await media_world.session.execute(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == vibe.id)
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == ["live_vibe.published"]
    assert events[0].payload["expires_at"] == vibe.expires_at.isoformat()  # type: ignore[union-attr]


async def test_processing_continues_after_the_author_walks_out(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """Presence gates admission, not the pipeline. Leaving is not a cancellation."""
    payload = write_png(tmp_path / "left.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    await media_world.clear_lease()

    runner = pipeline(media_world, object_storage)
    await runner.validate_and_process(asset_id, now=NOW)
    await runner.moderate(asset_id, now=NOW)
    assert (await load_vibe(media_world, asset_id)).publication_status == "published"


# ------------------------------------------------------------- refusal paths


async def test_malware_quarantines_and_rejects_the_post(
    media_world: MediaWorld, object_storage: ObjectStorage
) -> None:
    payload = EICAR_SIGNATURE + b"-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    asset_id = await accepted_upload(media_world, object_storage, payload)

    outcome = await pipeline(media_world, object_storage).validate_and_process(asset_id, now=NOW)
    assert outcome.status == "quarantined"

    asset = await load_asset(media_world, asset_id)
    assert asset.moderation_status == "quarantined"
    assert asset.lifecycle_status == "manual_review"
    assert asset.moderation_summary["malware_signature"] == "EICAR-Test"
    assert (await load_vibe(media_world, asset_id)).publication_status == "rejected"
    assert await load_derivatives(media_world, asset_id) == []


async def test_a_scanner_that_cannot_run_holds_the_media_rather_than_passing_it(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "unscanned.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)

    outcome = await pipeline(
        media_world, object_storage, scanner=FailClosedMalwareScanner("clamav")
    ).validate_and_process(asset_id, now=NOW)
    assert outcome.status == "quarantined"

    asset = await load_asset(media_world, asset_id)
    assert asset.moderation_status == "quarantined"
    assert asset.moderation_summary["malware_verdict"] == "unavailable"
    # No malware was proven, so the post is held rather than rejected outright.
    assert (await load_vibe(media_world, asset_id)).publication_status == "processing"


async def test_bytes_swapped_after_admission_are_caught_by_the_size_check(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """The presigned URL may still be live; the pipeline re-measures anyway."""
    payload = write_png(tmp_path / "declared.png", width=200, height=200).read_bytes()
    await media_world.grant_lease()
    media = MediaService(
        media_world.session, media_world.redis, media_world.settings, object_storage
    )
    response = await media.create_upload(
        user=media_world.author,
        request=CreateUploadRequest.model_validate(
            {
                "venue_id": str(media_world.venue_id),
                "device_id": str(media_world.device_id),
                "media_type": "image",
                "mime_type": "image/png",
                "byte_size": len(payload),
            }
        ),
        now=NOW,
    )
    await put_bytes(response.upload.url, response.upload.headers, payload)
    await media.complete_upload(
        user=media_world.author,
        upload_id=response.upload_id,
        request=CompleteUploadRequest(device_id=media_world.device_id),
        now=NOW,
    )
    swapped = write_png(tmp_path / "swapped.png", width=900, height=700).read_bytes()
    assert len(swapped) != len(payload)
    await put_bytes(response.upload.url, response.upload.headers, swapped)

    outcome = await pipeline(media_world, object_storage).validate_and_process(
        response.upload_id, now=NOW
    )
    assert outcome.status == "invalid"
    asset = await load_asset(media_world, response.upload_id)
    assert asset.lifecycle_status == "invalid"
    assert asset.moderation_summary["invalid_reason"] == "byte_size_mismatch"
    assert (await load_vibe(media_world, response.upload_id)).publication_status == "rejected"


async def test_content_that_is_not_an_image_is_invalid_not_retried(
    media_world: MediaWorld, object_storage: ObjectStorage
) -> None:
    payload = b"this is plainly not an image" * 4
    asset_id = await accepted_upload(media_world, object_storage, payload)

    outcome = await pipeline(media_world, object_storage).validate_and_process(asset_id, now=NOW)
    assert outcome.status == "invalid"
    assert not outcome.should_retry
    asset = await load_asset(media_world, asset_id)
    assert asset.moderation_summary["invalid_reason"] == "mime_not_an_image"


async def test_a_rejecting_moderator_never_publishes(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "rejected.png").read_bytes()
    asset_id = await accepted_upload(
        media_world, object_storage, payload, caption="see this [moderation:reject]"
    )
    runner = pipeline(media_world, object_storage)
    await runner.validate_and_process(asset_id, now=NOW)
    outcome = await runner.moderate(asset_id, now=NOW)

    assert outcome.status == "rejected"
    asset = await load_asset(media_world, asset_id)
    assert (asset.lifecycle_status, asset.moderation_status) == ("rejected", "rejected")
    vibe = await load_vibe(media_world, asset_id)
    assert vibe.publication_status == "rejected"
    assert vibe.published_at is None


async def test_a_review_marker_holds_the_post_for_a_human(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "review.png").read_bytes()
    asset_id = await accepted_upload(
        media_world, object_storage, payload, vibe_tags=["moderation-review"]
    )
    runner = pipeline(media_world, object_storage)
    await runner.validate_and_process(asset_id, now=NOW)
    outcome = await runner.moderate(asset_id, now=NOW)

    assert outcome.status == "quarantined"
    asset = await load_asset(media_world, asset_id)
    assert (asset.lifecycle_status, asset.moderation_status) == ("manual_review", "manual_review")
    assert (await load_vibe(media_world, asset_id)).publication_status == "processing"


async def test_a_provider_exception_becomes_manual_review_not_an_approval(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "boom.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    runner = pipeline(media_world, object_storage, moderator=ExplodingModerationProvider())
    await runner.validate_and_process(asset_id, now=NOW)
    outcome = await runner.moderate(asset_id, now=NOW)

    assert outcome.status == "quarantined"
    assert (await load_asset(media_world, asset_id)).moderation_status == "manual_review"
    case = (
        await media_world.session.execute(
            select(ModerationCase).where(ModerationCase.media_asset_id == asset_id)
        )
    ).scalar_one()
    assert case.status == "needs_review"
    assert case.resolved_at is None


async def test_an_unreachable_object_store_is_a_retry_not_a_rejection(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    class BrokenDownload:
        def __init__(self, inner: ObjectStorage) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> object:
            return getattr(self._inner, name)

        async def download_to_path(self, *, bucket: str, key: str, destination: Path) -> None:
            raise OSError("connection reset")

    payload = write_png(tmp_path / "retry.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    outcome = await pipeline(media_world, BrokenDownload(object_storage)).validate_and_process(  # type: ignore[arg-type]
        asset_id, now=NOW
    )

    assert outcome.status == "retry"
    assert outcome.should_retry
    asset = await load_asset(media_world, asset_id)
    assert asset.lifecycle_status == "processing_failed"
    assert asset.moderation_summary["error_category"] == "download"


async def test_a_retry_writes_a_new_generation_and_retires_the_old_one(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """A reprocess must not overwrite bytes a live signed URL still points at."""
    payload = write_png(tmp_path / "gen.png", width=800, height=600).read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    runner = pipeline(media_world, object_storage)
    await runner.validate_and_process(asset_id, now=NOW)

    asset = await load_asset(media_world, asset_id)
    asset.lifecycle_status = "processing_failed"
    await media_world.session.commit()

    await runner.validate_and_process(asset_id, now=NOW)
    derivatives = await load_derivatives(media_world, asset_id)
    generations = {d.generation for d in derivatives}
    assert generations == {1, 2}
    assert {d.status for d in derivatives if d.generation == 1} == {"deleted"}
    assert {d.status for d in derivatives if d.generation == 2} == {"ready"}
    assert (await load_asset(media_world, asset_id)).generation == 2


async def test_the_pipeline_declines_work_for_an_asset_in_the_wrong_state(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "twice.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    runner = pipeline(media_world, object_storage)
    await runner.validate_and_process(asset_id, now=NOW)

    # A duplicate delivery of the same job finds the asset already processed.
    repeated = await runner.validate_and_process(asset_id, now=NOW)
    assert repeated.status == "skipped"
    assert repeated.detail == "moderation_pending"

    missing = await runner.moderate(uuid4(), now=NOW)
    assert missing.status == "skipped"
    assert missing.detail == "asset_missing"


# --------------------------------------------------------------------- job queue


async def test_a_claimed_job_is_invisible_to_a_second_worker(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "claim.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    store = MediaJobStore(media_world.session, media_world.settings)

    claimed = await store.claim(job_types=["validate_process"], owner="worker-a", limit=10, now=NOW)
    mine = [job for job in claimed if job.media_asset_id == asset_id]
    assert len(mine) == 1
    assert mine[0].attempt_count == 1

    again = await store.claim(job_types=["validate_process"], owner="worker-b", limit=10, now=NOW)
    assert asset_id not in {job.media_asset_id for job in again}


async def test_a_crashed_worker_lease_is_returned_to_the_queue(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "stale.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    store = MediaJobStore(media_world.session, media_world.settings)
    claimed = await store.claim(job_types=["validate_process"], owner="crashed", limit=10, now=NOW)
    job = next(job for job in claimed if job.media_asset_id == asset_id)

    much_later = NOW + timedelta(hours=6)
    assert await store.reclaim_stale_leases(now=much_later) >= 1
    requeued = await store.claim(
        job_types=["validate_process"], owner="worker-b", limit=10, now=much_later
    )
    assert job.id in {candidate.id for candidate in requeued}


async def test_failures_back_off_and_eventually_dead_letter(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "dead.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    settings = media_world.settings.model_copy(update={"media_processing_max_attempts": 2})
    store = MediaJobStore(media_world.session, settings)
    claimed = await store.claim(job_types=["validate_process"], owner="w", limit=10, now=NOW)
    job = next(job for job in claimed if job.media_asset_id == asset_id)

    assert await store.mark_failed(job.id, now=NOW, attempt_count=1, error_category="x") == "failed"
    scheduled = (
        await media_world.session.execute(
            text("SELECT next_attempt_at FROM app.media_processing_jobs WHERE id = :id"),
            {"id": str(job.id)},
        )
    ).scalar_one()
    assert scheduled > NOW

    final = await store.mark_failed(job.id, now=NOW, attempt_count=2, error_category="x")
    assert final == "dead_letter"
    # A dead letter is never claimed again.
    assert job.id not in {
        candidate.id
        for candidate in await store.claim(
            job_types=["validate_process"], owner="w", limit=10, now=NOW + timedelta(days=1)
        )
    }


# ---------------------------------------------------------------------- retention


async def test_expired_windows_stop_being_public(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "expire.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    runner = pipeline(media_world, object_storage)
    await runner.validate_and_process(asset_id, now=NOW)
    await runner.moderate(asset_id, now=NOW)
    vibe = await load_vibe(media_world, asset_id)
    assert vibe.expires_at is not None

    retention = MediaRetentionService(media_world.session, media_world.settings, object_storage)
    assert await retention.expire_due_vibes(now=vibe.expires_at + timedelta(minutes=1)) >= 1
    assert (await load_vibe(media_world, asset_id)).publication_status == "expired"


async def test_an_abandoned_upload_and_its_object_are_removed(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "abandoned.png").read_bytes()
    await media_world.grant_lease()
    media = MediaService(
        media_world.session, media_world.redis, media_world.settings, object_storage
    )
    long_ago = NOW - timedelta(hours=48)
    response = await media.create_upload(
        user=media_world.author,
        request=CreateUploadRequest.model_validate(
            {
                "venue_id": str(media_world.venue_id),
                "device_id": str(media_world.device_id),
                "media_type": "image",
                "mime_type": "image/png",
                "byte_size": len(payload),
            }
        ),
        now=long_ago,
    )
    # The client uploaded bytes and then vanished without completing.
    await put_bytes(response.upload.url, response.upload.headers, payload)
    asset = await load_asset(media_world, response.upload_id)
    key = asset.quarantine_object_key
    assert (
        await object_storage.stat_object(
            bucket=media_world.settings.media_quarantine_bucket, key=key
        )
        is not None
    )

    retention = MediaRetentionService(media_world.session, media_world.settings, object_storage)
    assert await retention.purge_incomplete_uploads(now=NOW) >= 1

    purged = await load_asset(media_world, response.upload_id)
    assert purged.lifecycle_status == "deleted"
    assert purged.deleted_reason == "retention_incomplete_upload"
    assert (await load_vibe(media_world, response.upload_id)).publication_status == "deleted"
    assert (
        await object_storage.stat_object(
            bucket=media_world.settings.media_quarantine_bucket, key=key
        )
        is None
    )


async def test_the_quarantined_original_is_dropped_once_derivatives_have_served(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "original.png", width=700, height=500).read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    runner = pipeline(media_world, object_storage)
    await runner.validate_and_process(asset_id, now=NOW)
    await runner.moderate(asset_id, now=NOW)
    asset = await load_asset(media_world, asset_id)
    key = asset.quarantine_object_key

    retention = MediaRetentionService(media_world.session, media_world.settings, object_storage)
    later = NOW + timedelta(hours=media_world.settings.retention_processed_original_hours + 1)
    assert await retention.purge_processed_originals(now=later) >= 1
    assert (
        await object_storage.stat_object(
            bucket=media_world.settings.media_quarantine_bucket, key=key
        )
        is None
    )
    # Derivatives keep serving; only the original went away.
    assert {d.status for d in await load_derivatives(media_world, asset_id)} == {"ready"}
    assert "original_purged_at" in (await load_asset(media_world, asset_id)).moderation_summary

    # A second sweep finds nothing left to do for this asset.
    assert await retention.purge_processed_originals(now=later) == 0


async def test_derivatives_outlive_the_public_window_only_briefly(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "derivatives.png").read_bytes()
    asset_id = await accepted_upload(media_world, object_storage, payload)
    runner = pipeline(media_world, object_storage)
    await runner.validate_and_process(asset_id, now=NOW)
    await runner.moderate(asset_id, now=NOW)
    vibe = await load_vibe(media_world, asset_id)
    assert vibe.expires_at is not None
    keys = [d.object_key for d in await load_derivatives(media_world, asset_id)]

    retention = MediaRetentionService(media_world.session, media_world.settings, object_storage)
    await retention.expire_due_vibes(now=vibe.expires_at + timedelta(minutes=1))

    just_after = vibe.expires_at + timedelta(days=1)
    assert await retention.purge_expired_derivatives(now=just_after) == 0

    well_after = vibe.expires_at + timedelta(
        days=media_world.settings.retention_processed_derivative_days + 1
    )
    assert await retention.purge_expired_derivatives(now=well_after) >= 1
    assert {d.status for d in await load_derivatives(media_world, asset_id)} == {"deleted"}
    for key in keys:
        assert (
            await object_storage.stat_object(
                bucket=media_world.settings.media_processed_bucket, key=key
            )
            is None
        )


async def test_a_rejected_original_is_kept_as_evidence_then_purged(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    payload = write_png(tmp_path / "evidence.png").read_bytes()
    asset_id = await accepted_upload(
        media_world, object_storage, payload, caption="[moderation:reject] no"
    )
    runner = pipeline(media_world, object_storage)
    await runner.validate_and_process(asset_id, now=NOW)
    await runner.moderate(asset_id, now=NOW)
    key = (await load_asset(media_world, asset_id)).quarantine_object_key

    retention = MediaRetentionService(media_world.session, media_world.settings, object_storage)
    assert await retention.purge_rejected_originals(now=NOW) == 0

    later = NOW + timedelta(days=media_world.settings.retention_rejected_original_days + 1)
    assert await retention.purge_rejected_originals(now=later) >= 1
    assert (
        await object_storage.stat_object(
            bucket=media_world.settings.media_quarantine_bucket, key=key
        )
        is None
    )


def test_retention_windows_match_the_documented_policy() -> None:
    settings = Settings(auth_provider="cognito")
    assert settings.retention_incomplete_upload_hours == 24
    assert settings.retention_processed_original_hours == 24
    assert settings.retention_rejected_original_days == 3
    assert settings.retention_processed_derivative_days == 7
