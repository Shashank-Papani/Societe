"""Reading a venue's feed, reporting a post, and deleting your own.

Reading requires an account but not presence: someone deciding whether to walk
into a bar is not standing in it yet. Everything else here is about what the feed
must never contain — unmoderated media, expired posts, private object keys, or an
identifier attached to an anonymous vibe.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from media_support import MediaWorld, put_bytes
from societe_media_fixtures import write_png
from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import ContentReport, LiveVibe, MediaAsset, MediaDerivative, OutboxEvent, User
from app.modules.media.pipeline import MediaPipeline
from app.modules.media.schemas import (
    CompleteUploadRequest,
    CreateReportRequest,
    CreateUploadRequest,
)
from app.modules.media.service import MediaService
from app.modules.media.storage import ObjectStorage
from app.modules.vibes.service import VibeService
from app.shared.cursors import keyset_fingerprint, sign_keyset_cursor

#: Fixed, and deliberately mid-afternoon at the venue. Expiry is `min(next 06:00
#: local, published_at + max lifetime)`, so a wall-clock "now" would make these
#: assertions pass or fail depending on the hour the suite happened to run.
NOW = datetime(2026, 8, 20, 20, 0, tzinfo=UTC)


async def publish_vibe(
    world: MediaWorld,
    storage: ObjectStorage,
    tmp_path: Path,
    *,
    ghost_mode: bool = False,
    caption: str = "packed dance floor",
    now: datetime | None = None,
) -> UUID:
    """Take one post all the way to `published` and return its vibe id."""
    moment = now or NOW
    payload = write_png(tmp_path / f"{uuid4().hex}.png", width=600, height=400).read_bytes()
    await world.grant_lease(ghost_mode=ghost_mode, now=moment)
    media = MediaService(world.session, world.redis, world.settings, storage)
    response = await media.create_upload(
        user=world.author,
        request=CreateUploadRequest.model_validate(
            {
                "venue_id": str(world.venue_id),
                "device_id": str(world.device_id),
                "media_type": "image",
                "mime_type": "image/png",
                "byte_size": len(payload),
                "caption": caption,
                "vibe_tags": ["rooftop"],
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
    runner = MediaPipeline(world.session, world.settings, storage=storage)
    await runner.validate_and_process(response.upload_id, now=moment)
    await runner.moderate(response.upload_id, now=moment)
    return response.live_vibe_id


def vibes(world: MediaWorld, storage: ObjectStorage) -> VibeService:
    return VibeService(world.session, world.redis, world.settings, storage)


async def load_vibe(world: MediaWorld, vibe_id: UUID) -> LiveVibe:
    await world.session.commit()
    result = await world.session.execute(select(LiveVibe).where(LiveVibe.id == vibe_id))
    return result.scalar_one()


# ----------------------------------------------------------------------- feed


async def test_a_published_vibe_appears_with_signed_variants(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    feed = await vibes(media_world, object_storage).venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.viewer,
        cursor=None,
        limit=10,
        now=NOW,
    )
    assert [item.id for item in feed.items] == [vibe_id]
    item = feed.items[0]
    assert item.caption == "packed dance floor"
    assert item.vibe_tags == ["rooftop"]
    assert item.media_type == "image"
    assert {variant.variant_type for variant in item.variants} == {
        "image_1080",
        "image_720",
        "thumbnail",
    }
    for variant in item.variants:
        assert "X-Amz-Signature=" in variant.url
        assert variant.expires_at == NOW + timedelta(
            seconds=media_world.settings.media_signed_url_ttl_seconds
        )


async def test_the_feed_is_readable_without_being_at_the_venue(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """Browsing is not posting: no lease is required to look."""
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    await media_world.clear_lease()
    feed = await vibes(media_world, object_storage).venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.viewer,
        cursor=None,
        limit=10,
        now=NOW,
    )
    assert [item.id for item in feed.items] == [vibe_id]


async def test_object_keys_never_appear_in_the_feed(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await publish_vibe(media_world, object_storage, tmp_path)
    feed = await vibes(media_world, object_storage).venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.viewer,
        cursor=None,
        limit=10,
        now=NOW,
    )
    keys = (
        (
            await media_world.session.execute(
                select(MediaDerivative.object_key).where(MediaDerivative.status == "ready")
            )
        )
        .scalars()
        .all()
    )
    body = feed.model_dump_json()
    stripped = body
    for item in feed.items:
        for variant in item.variants:
            stripped = stripped.replace(variant.url, "")
    for key in keys:
        assert key not in stripped


async def test_an_anonymous_vibe_carries_no_identifier_at_all(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """Even an opaque author id would let posts be correlated to one person."""
    await publish_vibe(media_world, object_storage, tmp_path, ghost_mode=True)
    feed = await vibes(media_world, object_storage).venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.viewer,
        cursor=None,
        limit=10,
        now=NOW,
    )
    item = feed.items[0]
    assert item.attribution_mode == "anonymous"
    assert item.author is None
    assert item.author_label == "Anonymous"

    author = (
        await media_world.session.execute(select(User).where(User.id == media_world.author_id))
    ).scalar_one()
    body = feed.model_dump_json()
    assert str(media_world.author_id) not in body
    assert author.handle not in body
    assert author.display_name not in body


async def test_an_attributed_vibe_names_its_author(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await publish_vibe(media_world, object_storage, tmp_path)
    feed = await vibes(media_world, object_storage).venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.viewer,
        cursor=None,
        limit=10,
        now=NOW,
    )
    author = feed.items[0].author
    assert author is not None
    assert author.id == media_world.author_id
    assert feed.items[0].viewer_is_author is False


async def test_the_author_sees_their_own_post_marked(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await publish_vibe(media_world, object_storage, tmp_path)
    feed = await vibes(media_world, object_storage).venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.author,
        cursor=None,
        limit=10,
        now=NOW,
    )
    assert feed.items[0].viewer_is_author is True


async def test_an_expired_window_removes_the_post_from_the_feed(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """Visibility follows `expires_at`, not a later sweep by the worker."""
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    vibe = await load_vibe(media_world, vibe_id)
    assert vibe.expires_at is not None

    feed = await vibes(media_world, object_storage).venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.viewer,
        cursor=None,
        limit=10,
        now=vibe.expires_at + timedelta(seconds=1),
    )
    assert feed.items == []


async def test_creator_still_sees_expired_vibe_metadata(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    vibe = await load_vibe(media_world, vibe_id)
    assert vibe.expires_at is not None
    vibe.publication_status = "expired"
    await media_world.session.commit()

    after_expiry = vibe.expires_at + timedelta(hours=1)
    mine = await vibes(media_world, object_storage).creator_vibes(
        author=media_world.author,
        cursor=None,
        limit=10,
        now=after_expiry,
    )
    assert len(mine.items) == 1
    assert mine.items[0].id == vibe_id
    assert mine.items[0].publication_status == "expired"
    # Still inside the 7-day creator retention window, so URLs may still mint.
    assert mine.items[0].variants

    past_retention = vibe.expires_at + timedelta(days=8)
    mine_later = await vibes(media_world, object_storage).creator_vibes(
        author=media_world.author,
        cursor=None,
        limit=10,
        now=past_retention,
    )
    assert mine_later.items[0].publication_status == "expired"
    assert mine_later.items[0].variants == []


@pytest.mark.parametrize("status", ["draft", "processing", "hidden", "rejected"])
async def test_unpublished_states_are_never_served(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path, status: str
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    vibe = await load_vibe(media_world, vibe_id)
    vibe.publication_status = status
    await media_world.session.commit()

    feed = await vibes(media_world, object_storage).venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.viewer,
        cursor=None,
        limit=10,
        now=NOW,
    )
    assert feed.items == []


async def test_a_published_vibe_whose_media_is_not_ready_is_withheld(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """Two conditions, both required: publication and approved media."""
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    vibe = await load_vibe(media_world, vibe_id)
    asset = (
        await media_world.session.execute(
            select(MediaAsset).where(MediaAsset.id == vibe.media_asset_id)
        )
    ).scalar_one()
    asset.moderation_status = "manual_review"
    await media_world.session.commit()

    feed = await vibes(media_world, object_storage).venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.viewer,
        cursor=None,
        limit=10,
        now=NOW,
    )
    assert feed.items == []


async def test_another_venues_feed_does_not_include_this_one(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await publish_vibe(media_world, object_storage, tmp_path)
    feed = await vibes(media_world, object_storage).venue_feed(
        venue_id=uuid4(),
        viewer=media_world.viewer,
        cursor=None,
        limit=10,
        now=NOW,
    )
    assert feed.items == []


async def test_pages_are_newest_first_and_the_cursor_continues_exactly_once(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    first = await publish_vibe(media_world, object_storage, tmp_path, now=NOW - timedelta(hours=3))
    second = await publish_vibe(media_world, object_storage, tmp_path, now=NOW - timedelta(hours=2))
    third = await publish_vibe(media_world, object_storage, tmp_path, now=NOW - timedelta(hours=1))

    service = vibes(media_world, object_storage)
    page_one = await service.venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.viewer,
        cursor=None,
        limit=2,
        now=NOW,
    )
    assert [item.id for item in page_one.items] == [third, second]
    assert page_one.next_cursor is not None

    page_two = await service.venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.viewer,
        cursor=page_one.next_cursor,
        limit=2,
        now=NOW,
    )
    assert [item.id for item in page_two.items] == [first]
    assert page_two.next_cursor is None


async def test_a_tampered_cursor_is_rejected(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    await publish_vibe(media_world, object_storage, tmp_path)
    service = vibes(media_world, object_storage)
    with pytest.raises(AppError) as exc:
        await service.venue_feed(
            venue_id=media_world.venue_id,
            viewer=media_world.viewer,
            cursor="not-even-close.signature",
            limit=5,
            now=NOW,
        )
    assert exc.value.code == "CURSOR_INVALID"


async def test_a_cursor_from_another_venue_is_rejected(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    """Otherwise a cursor becomes a way to seek into a different query."""
    await publish_vibe(media_world, object_storage, tmp_path)
    foreign = sign_keyset_cursor(
        sort_key=NOW.isoformat(),
        item_id=str(uuid4()),
        qfp=keyset_fingerprint(feed="venue_live_vibes", venue_id=str(uuid4())),
        secret=media_world.settings.cursor_hmac_secret.get_secret_value(),
    )
    with pytest.raises(AppError) as exc:
        await vibes(media_world, object_storage).venue_feed(
            venue_id=media_world.venue_id,
            viewer=media_world.viewer,
            cursor=foreign,
            limit=5,
            now=NOW,
        )
    assert exc.value.code == "CURSOR_QUERY_MISMATCH"


# --------------------------------------------------------------------- reports


async def test_a_report_is_recorded_and_emits_an_event(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    response = await vibes(media_world, object_storage).report(
        reporter=media_world.viewer,
        vibe_id=vibe_id,
        request=CreateReportRequest(reason="harassment", description="targeted at me"),
        now=NOW,
    )
    assert response.reason == "harassment"
    assert response.status == "open"
    # One report is not a takedown button.
    assert response.content_hidden is False
    assert (await load_vibe(media_world, vibe_id)).publication_status == "published"

    events = (
        (
            await media_world.session.execute(
                select(OutboxEvent).where(
                    OutboxEvent.aggregate_id == vibe_id,
                    OutboxEvent.event_type == "content.reported",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1
    assert events[0].payload["auto_hidden"] is False


async def test_the_same_reporter_cannot_report_twice(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    service = vibes(media_world, object_storage)
    await service.report(
        reporter=media_world.viewer,
        vibe_id=vibe_id,
        request=CreateReportRequest(reason="spam"),
        now=NOW,
    )
    with pytest.raises(AppError) as exc:
        await service.report(
            reporter=media_world.viewer,
            vibe_id=vibe_id,
            request=CreateReportRequest(reason="spam"),
            now=NOW,
        )
    assert exc.value.code == "REPORT_ALREADY_SUBMITTED"
    assert exc.value.status_code == 409

    reports = (
        (
            await media_world.session.execute(
                select(ContentReport).where(ContentReport.live_vibe_id == vibe_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(reports) == 1


async def test_you_cannot_report_your_own_post(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    with pytest.raises(AppError) as exc:
        await vibes(media_world, object_storage).report(
            reporter=media_world.author,
            vibe_id=vibe_id,
            request=CreateReportRequest(reason="other"),
            now=NOW,
        )
    assert exc.value.code == "CANNOT_REPORT_OWN_CONTENT"


async def test_an_over_long_description_is_refused(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    limit = media_world.settings.vibe_report_description_max_length
    with pytest.raises(AppError) as exc:
        await vibes(media_world, object_storage).report(
            reporter=media_world.viewer,
            vibe_id=vibe_id,
            request=CreateReportRequest(reason="other", description="x" * (limit + 1)),
            now=NOW,
        )
    assert exc.value.code == "REPORT_DESCRIPTION_TOO_LONG"
    assert exc.value.details["max_length"] == limit


async def test_reporting_an_unknown_vibe_is_a_not_found(
    media_world: MediaWorld, object_storage: ObjectStorage
) -> None:
    with pytest.raises(AppError) as exc:
        await vibes(media_world, object_storage).report(
            reporter=media_world.viewer,
            vibe_id=uuid4(),
            request=CreateReportRequest(reason="spam"),
            now=NOW,
        )
    assert exc.value.status_code == 404


async def test_auto_hide_only_happens_when_a_threshold_is_configured(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    assert media_world.settings.vibe_report_auto_hide_threshold == 0

    with_threshold = media_world.settings.model_copy(update={"vibe_report_auto_hide_threshold": 1})
    service = VibeService(media_world.session, media_world.redis, with_threshold, object_storage)
    response = await service.report(
        reporter=media_world.viewer,
        vibe_id=vibe_id,
        request=CreateReportRequest(reason="hate"),
        now=NOW,
    )
    assert response.content_hidden is True

    hidden = await load_vibe(media_world, vibe_id)
    assert hidden.publication_status == "hidden"
    assert hidden.hidden_reason == "report_threshold"

    feed = await vibes(media_world, object_storage).venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.viewer,
        cursor=None,
        limit=10,
        now=NOW,
    )
    assert feed.items == []


async def test_report_budgets_are_enforced_per_account(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    throttled = media_world.settings.model_copy(
        update={"vibe_report_rate_limit_per_user_per_hour": 0}
    )
    service = VibeService(media_world.session, media_world.redis, throttled, object_storage)
    with pytest.raises(AppError) as exc:
        await service.report(
            reporter=media_world.viewer,
            vibe_id=vibe_id,
            request=CreateReportRequest(reason="spam"),
            now=NOW,
        )
    assert exc.value.status_code == 429


# ---------------------------------------------------------------------- delete


async def test_the_author_can_delete_their_post_and_its_media(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    response = await vibes(media_world, object_storage).delete(
        user=media_world.author, vibe_id=vibe_id, now=NOW
    )
    assert response.publication_status == "deleted"

    vibe = await load_vibe(media_world, vibe_id)
    asset = (
        await media_world.session.execute(
            select(MediaAsset).where(MediaAsset.id == vibe.media_asset_id)
        )
    ).scalar_one()
    assert asset.lifecycle_status == "deleted"
    assert asset.deleted_reason == "author_deleted"

    feed = await vibes(media_world, object_storage).venue_feed(
        venue_id=media_world.venue_id,
        viewer=media_world.viewer,
        cursor=None,
        limit=10,
        now=NOW,
    )
    assert feed.items == []


async def test_someone_else_cannot_delete_your_post(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    with pytest.raises(AppError) as exc:
        await vibes(media_world, object_storage).delete(
            user=media_world.viewer, vibe_id=vibe_id, now=NOW
        )
    assert exc.value.status_code == 404
    assert (await load_vibe(media_world, vibe_id)).publication_status == "published"


async def test_deleting_twice_reports_not_found(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    service = vibes(media_world, object_storage)
    await service.delete(user=media_world.author, vibe_id=vibe_id, now=NOW)
    with pytest.raises(AppError) as exc:
        await service.delete(user=media_world.author, vibe_id=vibe_id, now=NOW)
    assert exc.value.status_code == 404


async def test_a_deleted_post_cannot_be_reported(
    media_world: MediaWorld, object_storage: ObjectStorage, tmp_path: Path
) -> None:
    vibe_id = await publish_vibe(media_world, object_storage, tmp_path)
    service = vibes(media_world, object_storage)
    await service.delete(user=media_world.author, vibe_id=vibe_id, now=NOW)
    with pytest.raises(AppError) as exc:
        await service.report(
            reporter=media_world.viewer,
            vibe_id=vibe_id,
            request=CreateReportRequest(reason="spam"),
            now=NOW,
        )
    assert exc.value.status_code == 404
