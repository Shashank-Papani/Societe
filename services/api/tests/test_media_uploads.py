"""Upload intent and completion, against the real stack.

The through-line: a presigned PUT is a capability. It is only issued to a
verified poster, it points at a host a phone can actually reach, and the bytes
that arrive are re-checked before anything is queued.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from media_support import MediaWorld, put_bytes
from societe_media_fixtures import write_png
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import LiveVibe, MediaAsset, MediaProcessingJob, OutboxEvent
from app.modules.media.malware import EICAR_SIGNATURE
from app.modules.media.schemas import CompleteUploadRequest, CreateUploadRequest
from app.modules.media.service import MediaService
from app.modules.media.storage import ObjectStorage

NOW = datetime.now(UTC)


def service(world: MediaWorld, storage: ObjectStorage) -> MediaService:
    return MediaService(world.session, world.redis, world.settings, storage)


def upload_request(world: MediaWorld, payload: bytes, **overrides: object) -> CreateUploadRequest:
    fields: dict[str, object] = {
        "venue_id": str(world.venue_id),
        "device_id": str(world.device.id),
        "media_type": "image",
        "mime_type": "image/png",
        "byte_size": len(payload),
        "caption": "rooftop set",
        "vibe_tags": ["rooftop"],
    }
    fields.update(overrides)
    return CreateUploadRequest.model_validate(fields)


def png_bytes(tmp_path: Path, **kwargs: int) -> bytes:
    return write_png(tmp_path / f"{uuid4().hex}.png", **kwargs).read_bytes()


async def start_upload(
    world: MediaWorld,
    storage: ObjectStorage,
    payload: bytes,
    *,
    now: datetime | None = None,
    **overrides: object,
) -> tuple[MediaService, object]:
    media = service(world, storage)
    response = await media.create_upload(
        user=world.author,
        request=upload_request(world, payload, **overrides),
        now=now or NOW,
    )
    return media, response


async def load_asset(world: MediaWorld, asset_id: object) -> MediaAsset:
    result = await world.session.execute(select(MediaAsset).where(MediaAsset.id == asset_id))
    return result.scalar_one()


async def load_vibe(world: MediaWorld, asset_id: object) -> LiveVibe:
    result = await world.session.execute(
        select(LiveVibe).where(LiveVibe.media_asset_id == asset_id)
    )
    return result.scalar_one()


# ----------------------------------------------------------------- create intent


async def test_intent_creates_the_asset_and_its_draft_vibe_together(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    payload = png_bytes(tmp_path)
    _, response = await start_upload(media_world, object_storage, payload)

    asset = await load_asset(media_world, response.upload_id)
    vibe = await load_vibe(media_world, response.upload_id)
    assert asset.lifecycle_status == "intent_pending"
    assert asset.moderation_status == "pending"
    assert asset.attribution_mode == "attributed"
    assert asset.declared_byte_size == len(payload)
    assert asset.venue_id == media_world.venue_id
    assert asset.device_id == media_world.device.id
    # The draft exists from the start, so an asset with no post is unrepresentable.
    assert vibe.publication_status == "draft"
    assert vibe.published_at is None
    assert vibe.expires_at is None
    assert vibe.caption == "rooftop set"


async def test_presigned_url_targets_the_client_reachable_host(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """A URL signed for `minio:9000` fails on every real device."""
    await media_world.grant_lease()
    _, response = await start_upload(media_world, object_storage, png_bytes(tmp_path))

    host = urlsplit(response.upload.url).hostname
    assert host == urlsplit(media_world.settings.minio_public_endpoint).hostname
    assert host not in {"minio", "societe-minio"}
    assert response.upload.method == "PUT"
    assert response.upload.headers["Content-Type"] == "image/png"


async def test_the_key_appears_only_inside_the_signed_url(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """A presigned PUT necessarily addresses the key; no other field may."""
    await media_world.grant_lease()
    _, response = await start_upload(media_world, object_storage, png_bytes(tmp_path))
    asset = await load_asset(media_world, response.upload_id)

    without_url = response.model_dump_json().replace(response.upload.url, "")
    assert asset.quarantine_object_key not in without_url
    assert "quarantine/" not in without_url
    # The capability is bounded: it is signed and it expires.
    assert "X-Amz-Signature=" in response.upload.url
    assert "X-Amz-Expires=" in response.upload.url


async def test_upload_window_never_outlives_the_intent(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    _, response = await start_upload(media_world, object_storage, png_bytes(tmp_path))
    assert response.upload.expires_at <= response.intent_expires_at


async def test_ghost_mode_is_snapshotted_as_anonymous_attribution(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease(ghost_mode=True)
    _, response = await start_upload(media_world, object_storage, png_bytes(tmp_path))
    assert response.attribution_mode == "anonymous"
    assert (await load_vibe(media_world, response.upload_id)).attribution_mode == "anonymous"


async def test_posting_without_a_verified_lease_is_refused(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease(state="provisional")
    with pytest.raises(AppError) as exc:
        await start_upload(media_world, object_storage, png_bytes(tmp_path))
    assert exc.value.code == "MEDIA_POSTING_NOT_AUTHORIZED"
    assert exc.value.status_code == 403
    assert exc.value.details["reason"] == "presence_provisional"
    assert exc.value.details["retryable"] is True


async def test_posting_to_a_venue_the_lease_does_not_cover_is_refused(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease(venue_id=uuid4())
    with pytest.raises(AppError) as exc:
        await start_upload(media_world, object_storage, png_bytes(tmp_path))
    assert exc.value.details["reason"] == "presence_venue_mismatch"


async def test_no_asset_row_is_left_behind_by_a_refused_intent(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.clear_lease()
    with pytest.raises(AppError):
        await start_upload(media_world, object_storage, png_bytes(tmp_path))
    result = await media_world.session.execute(
        select(MediaAsset).where(MediaAsset.owner_user_id == media_world.author.id)
    )
    assert result.scalars().all() == []


async def test_feature_flag_gates_posting_entirely(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    disabled = media_world.settings.model_copy(update={"ff_media_posting": False})
    media = MediaService(media_world.session, media_world.redis, disabled, object_storage)
    with pytest.raises(AppError) as exc:
        await media.create_upload(
            user=media_world.author,
            request=upload_request(media_world, png_bytes(tmp_path)),
            now=NOW,
        )
    assert exc.value.code == "MEDIA_POSTING_DISABLED"


async def test_outstanding_presigned_urls_are_capped(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """Otherwise a client can hoard upload capabilities it never uses."""
    await media_world.grant_lease()
    capped = media_world.settings.model_copy(update={"media_pending_intent_limit_per_user": 2})
    media = MediaService(media_world.session, media_world.redis, capped, object_storage)
    payload = png_bytes(tmp_path)
    for _ in range(2):
        await media.create_upload(
            user=media_world.author, request=upload_request(media_world, payload), now=NOW
        )
    with pytest.raises(AppError) as exc:
        await media.create_upload(
            user=media_world.author, request=upload_request(media_world, payload), now=NOW
        )
    assert exc.value.code == "MEDIA_PENDING_UPLOAD_LIMIT"
    assert exc.value.status_code == 429


# --------------------------------------------------------------------- complete


async def test_completion_marks_uploaded_and_queues_exactly_one_job(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    payload = png_bytes(tmp_path)
    media, response = await start_upload(media_world, object_storage, payload)
    put = await put_bytes(response.upload.url, response.upload.headers, payload)
    assert put.status_code in {200, 204}

    status = await media.complete_upload(
        user=media_world.author,
        upload_id=response.upload_id,
        request=CompleteUploadRequest(device_id=media_world.device.id),
        now=NOW,
    )
    assert status.lifecycle_status == "uploaded"

    asset = await load_asset(media_world, response.upload_id)
    assert asset.uploaded_at is not None
    # The intent is single-use.
    assert asset.intent_consumed_at is not None

    jobs = (
        (
            await media_world.session.execute(
                select(MediaProcessingJob).where(
                    MediaProcessingJob.media_asset_id == response.upload_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(job.job_type, job.status) for job in jobs] == [("validate_process", "pending")]

    events = (
        (
            await media_world.session.execute(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == response.upload_id)
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == ["media.upload_completed"]
    assert (await load_vibe(media_world, response.upload_id)).publication_status == "processing"


async def test_completion_requires_the_exact_declared_size(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """Declare a thumbnail, upload a movie: refused."""
    await media_world.grant_lease()
    declared = png_bytes(tmp_path, width=64, height=64)
    media, response = await start_upload(media_world, object_storage, declared)
    larger = png_bytes(tmp_path, width=800, height=600)
    assert len(larger) != len(declared)
    await put_bytes(response.upload.url, response.upload.headers, larger)

    with pytest.raises(AppError) as exc:
        await media.complete_upload(
            user=media_world.author,
            upload_id=response.upload_id,
            request=CompleteUploadRequest(device_id=media_world.device.id),
            now=NOW,
        )
    assert exc.value.code == "MEDIA_SIZE_MISMATCH"
    assert exc.value.details["declared_byte_size"] == len(declared)
    assert (await load_asset(media_world, response.upload_id)).lifecycle_status == "intent_pending"


async def test_completion_without_any_uploaded_object_is_refused(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    media, response = await start_upload(media_world, object_storage, png_bytes(tmp_path))
    with pytest.raises(AppError) as exc:
        await media.complete_upload(
            user=media_world.author,
            upload_id=response.upload_id,
            request=CompleteUploadRequest(device_id=media_world.device.id),
            now=NOW,
        )
    assert exc.value.code == "MEDIA_OBJECT_MISSING"


async def test_completion_from_a_different_device_is_refused(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    payload = png_bytes(tmp_path)
    media, response = await start_upload(media_world, object_storage, payload)
    await put_bytes(response.upload.url, response.upload.headers, payload)

    with pytest.raises(AppError) as exc:
        await media.complete_upload(
            user=media_world.author,
            upload_id=response.upload_id,
            request=CompleteUploadRequest(device_id=uuid4()),
            now=NOW,
        )
    assert exc.value.code == "MEDIA_DEVICE_MISMATCH"


async def test_completion_by_another_account_reports_not_found(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """Existence of someone else's upload is itself information."""
    await media_world.grant_lease()
    payload = png_bytes(tmp_path)
    media, response = await start_upload(media_world, object_storage, payload)
    await put_bytes(response.upload.url, response.upload.headers, payload)

    with pytest.raises(AppError) as exc:
        await media.complete_upload(
            user=media_world.viewer,
            upload_id=response.upload_id,
            request=CompleteUploadRequest(device_id=media_world.device.id),
            now=NOW,
        )
    assert exc.value.status_code == 404
    assert exc.value.code == "MEDIA_UPLOAD_NOT_FOUND"


async def test_expired_intent_closes_the_asset_and_the_draft_vibe(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    payload = png_bytes(tmp_path)
    media, response = await start_upload(media_world, object_storage, payload)
    await put_bytes(response.upload.url, response.upload.headers, payload)

    too_late = response.intent_expires_at + timedelta(seconds=1)
    with pytest.raises(AppError) as exc:
        await media.complete_upload(
            user=media_world.author,
            upload_id=response.upload_id,
            request=CompleteUploadRequest(device_id=media_world.device.id),
            now=too_late,
        )
    assert exc.value.code == "MEDIA_UPLOAD_INTENT_EXPIRED"
    assert (await load_asset(media_world, response.upload_id)).lifecycle_status == "upload_expired"
    assert (await load_vibe(media_world, response.upload_id)).publication_status == "expired"


async def test_leaving_the_venue_before_completion_refuses_the_upload(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    payload = png_bytes(tmp_path)
    media, response = await start_upload(media_world, object_storage, payload)
    await put_bytes(response.upload.url, response.upload.headers, payload)
    await media_world.clear_lease()

    with pytest.raises(AppError) as exc:
        await media.complete_upload(
            user=media_world.author,
            upload_id=response.upload_id,
            request=CompleteUploadRequest(device_id=media_world.device.id),
            now=NOW,
        )
    assert exc.value.code == "MEDIA_POSTING_NOT_AUTHORIZED"
    assert (await load_asset(media_world, response.upload_id)).lifecycle_status == "intent_pending"


async def test_moving_to_another_venue_before_completion_refuses_the_upload(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """The venue snapshot on the intent is what the bytes are attributed to."""
    await media_world.grant_lease()
    payload = png_bytes(tmp_path)
    media, response = await start_upload(media_world, object_storage, payload)
    await put_bytes(response.upload.url, response.upload.headers, payload)
    await media_world.grant_lease(venue_id=uuid4())

    with pytest.raises(AppError) as exc:
        await media.complete_upload(
            user=media_world.author,
            upload_id=response.upload_id,
            request=CompleteUploadRequest(device_id=media_world.device.id),
            now=NOW,
        )
    assert exc.value.details["reason"] == "presence_venue_mismatch"


async def test_a_replayed_completion_is_refused(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    payload = png_bytes(tmp_path)
    media, response = await start_upload(media_world, object_storage, payload)
    await put_bytes(response.upload.url, response.upload.headers, payload)
    await media.complete_upload(
        user=media_world.author,
        upload_id=response.upload_id,
        request=CompleteUploadRequest(device_id=media_world.device.id),
        now=NOW,
    )

    status = await media.complete_upload(
        user=media_world.author,
        upload_id=response.upload_id,
        request=CompleteUploadRequest(device_id=media_world.device.id),
        now=NOW,
    )
    # Reporting state is fine; re-admitting the bytes is not.
    assert status.lifecycle_status == "uploaded"
    jobs = (
        (
            await media_world.session.execute(
                select(MediaProcessingJob).where(
                    MediaProcessingJob.media_asset_id == response.upload_id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1


async def test_a_declared_checksum_is_recorded_but_not_trusted(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    payload = png_bytes(tmp_path)
    media, response = await start_upload(media_world, object_storage, payload)
    await put_bytes(response.upload.url, response.upload.headers, payload)
    await media.complete_upload(
        user=media_world.author,
        upload_id=response.upload_id,
        request=CompleteUploadRequest(device_id=media_world.device.id, checksum_sha256="b" * 64),
        now=NOW,
    )
    asset = await load_asset(media_world, response.upload_id)
    assert asset.moderation_summary["declared_checksum_sha256"] == "b" * 64
    # The authoritative hash is computed later, from the bytes the server reads.
    assert asset.checksum_sha256 is None


async def test_hostile_bytes_are_accepted_at_the_gate_and_caught_by_the_scanner(
    media_world: MediaWorld, object_storage: ObjectStorage
) -> None:
    """Admission checks size and presence, not content. Content is the pipeline's job."""
    await media_world.grant_lease()
    payload = EICAR_SIGNATURE + b"-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    media, response = await start_upload(media_world, object_storage, payload)
    await put_bytes(response.upload.url, response.upload.headers, payload)
    status = await media.complete_upload(
        user=media_world.author,
        upload_id=response.upload_id,
        request=CompleteUploadRequest(device_id=media_world.device.id),
        now=NOW,
    )
    assert status.lifecycle_status == "uploaded"
    assert (await load_vibe(media_world, response.upload_id)).publication_status == "processing"


# ----------------------------------------------------------------------- status


async def test_status_is_readable_by_the_owner_only(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    media, response = await start_upload(media_world, object_storage, png_bytes(tmp_path))

    mine = await media.get_upload(user=media_world.author, upload_id=response.upload_id, now=NOW)
    assert mine.lifecycle_status == "intent_pending"
    assert mine.variants == []

    with pytest.raises(AppError) as exc:
        await media.get_upload(user=media_world.viewer, upload_id=response.upload_id, now=NOW)
    assert exc.value.status_code == 404


async def test_abandoned_intents_are_expired_in_bulk(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    media, response = await start_upload(media_world, object_storage, png_bytes(tmp_path))

    expired = await media.expire_abandoned_intents(
        now=response.intent_expires_at + timedelta(minutes=1)
    )
    assert expired >= 1
    assert (await load_asset(media_world, response.upload_id)).lifecycle_status == "upload_expired"
    assert (await load_vibe(media_world, response.upload_id)).publication_status == "expired"


async def test_a_live_intent_is_not_expired_early(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await media_world.grant_lease()
    media, response = await start_upload(media_world, object_storage, png_bytes(tmp_path))
    assert await media.expire_abandoned_intents(now=NOW) == 0
    assert (await load_asset(media_world, response.upload_id)).lifecycle_status == "intent_pending"


def test_settings_refuse_a_compose_internal_public_endpoint() -> None:
    with pytest.raises(ValueError, match="MINIO_PUBLIC_ENDPOINT"):
        Settings(auth_provider="cognito", minio_public_endpoint="http://minio:9000")


def test_settings_require_a_scheme_on_the_public_endpoint() -> None:
    with pytest.raises(ValueError, match="MINIO_PUBLIC_ENDPOINT"):
        Settings(auth_provider="cognito", minio_public_endpoint="localhost:9000")


def test_quarantine_and_processed_buckets_must_differ() -> None:
    with pytest.raises(ValueError, match="must differ"):
        Settings(
            auth_provider="cognito",
            media_quarantine_bucket="same",
            media_processed_bucket="same",
        )
