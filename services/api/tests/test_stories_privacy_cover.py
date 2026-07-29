"""Privacy, cover stability, moderation fail-closed, and publication idempotency."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from media_support import build_world
from organization_support import (
    auth_headers,
    claimable_venue,
    insert_venue_owned_media,
    me,
)
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from story_support import (
    insert_published_official_story,
    insert_published_user_story,
    insert_text_official_post,
)

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    LiveVibe,
    MediaAsset,
    OutboxEvent,
    Story,
    User,
    Venue,
)
from app.modules.organizations.cover import CoverService
from app.modules.stories.lifecycle import mark_deleted, mark_rejected
from app.modules.stories.publication import (
    publish_content_for_media_asset,
    reject_content_for_media_asset,
)
from app.modules.stories.schemas import (
    CompleteStoryUploadRequest,
    CreateOfficialStoryUploadRequest,
    CreateUserStoryUploadRequest,
)
from app.modules.stories.service import StoryService


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


async def _link_venue(
    client: TestClient,
    db_session: AsyncSession,
    headers: dict[str, str],
) -> tuple[UUID, str, UUID]:
    venue = await claimable_venue(db_session)
    org = client.post(
        "/v1/organizations",
        headers=_idem(headers),
        json={"name": f"Privacy Org {uuid4().hex[:8]}"},
    )
    assert org.status_code == 201, org.text
    org_id = org.json()["data"]["id"]
    claim = client.post(
        f"/v1/venues/{venue.id}/claims",
        headers=_idem(headers),
        json={"organization_id": org_id},
    )
    assert claim.status_code == 201, claim.text
    approved = client.post(
        f"/v1/admin/venue-claims/{claim.json()['data']['id']}/approve",
        headers=headers,
    )
    assert approved.status_code == 200, approved.text
    return venue.id, org_id, venue.id


@pytest.mark.asyncio
async def test_anonymous_and_official_projections_hide_identity(
    client: TestClient,
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    headers = auth_headers(client, persona="alpha")
    venue_id, org_id, _ = await _link_venue(client, db_session, headers)
    owner = await db_session.get(User, UUID(me(client, headers)["id"]))
    assert owner is not None
    venue = await db_session.get(Venue, venue_id)
    assert venue is not None

    world = await build_world(db_session, valkey, media_settings)
    try:
        now = datetime.now(UTC)
        anon = await insert_published_user_story(
            db_session,
            user=world.author,
            venue_id=world.venue_id,
            check_in_id=world.check_in_id,
            device_id=world.device_id,
            attribution_mode="anonymous",
            now=now,
        )
        official = await insert_published_official_story(
            db_session,
            uploader=owner,
            venue_id=venue_id,
            organization_id=UUID(org_id),
            now=now,
        )
        service = StoryService(db_session, valkey, media_settings)
        groups = await service.list_experience_story_groups(viewer=world.viewer, now=now)
        anon_group = next(g for g in groups.items if g.group_type == "anon")
        official_group = next(g for g in groups.items if g.is_official)

        assert anon_group.author is None
        assert anon_group.author_label == "Anonymous"
        dumped_anon = anon_group.model_dump(mode="json")
        assert str(world.author_id) not in str(dumped_anon)
        assert world.author.handle not in str(dumped_anon)
        assert "avatar" not in str(dumped_anon).lower()
        assert "quarantine" not in str(dumped_anon)
        assert "object_key" not in str(dumped_anon)

        assert official_group.author is None
        assert official_group.author_label == venue.name
        assert official_group.is_official is True
        dumped_off = official_group.model_dump(mode="json")
        assert str(owner.id) not in str(dumped_off)
        assert owner.handle not in str(dumped_off)
        assert "created_by_user_id" not in dumped_off

        detail = await service.get_story_group(
            viewer=world.viewer, group_key=official_group.group_key, now=now
        )
        assert detail.slides[0].story_id == official.id
        assert detail.slides[0].author is None
        assert detail.slides[0].is_official is True
        assert detail.slides[0].attribution_mode == "official"
        # Media-layer attribution_mode stays attributed; public uses Story semantics.
        asset = await db_session.get(MediaAsset, official.media_asset_id)
        assert asset is not None
        assert asset.attribution_mode == "attributed"
        assert asset.purpose == "venue_owned"

        anon_detail = await service.get_story_group(
            viewer=world.viewer, group_key=anon_group.group_key, now=now
        )
        assert anon_detail.slides[0].story_id == anon.id
        assert anon_detail.slides[0].author is None
    finally:
        await world.cleanup()


@pytest.mark.asyncio
async def test_official_post_projection_hides_staff_identity(
    client: TestClient,
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    headers = auth_headers(client, persona="alpha")
    venue_id, org_id, _ = await _link_venue(client, db_session, headers)
    owner = await db_session.get(User, UUID(me(client, headers)["id"]))
    assert owner is not None
    venue = await db_session.get(Venue, venue_id)
    assert venue is not None

    post = await insert_text_official_post(
        db_session,
        user=owner,
        venue_id=venue_id,
        organization_id=UUID(org_id),
    )
    listed = client.get(f"/v1/venues/{venue_id}/official-posts", headers=headers)
    assert listed.status_code == 200, listed.text
    payload = listed.json()["data"]
    item = next(i for i in payload["items"] if i["post_id"] == str(post.id))
    assert item["is_official"] is True
    assert item["author_label"] == venue.name
    assert item["venue"]["id"] == str(venue_id)
    assert item["venue"]["name"] == venue.name
    blob = str(item)
    assert str(owner.id) not in blob
    assert owner.handle not in blob
    assert "created_by_user_id" not in blob
    assert "attribution_mode" not in blob
    assert "object_key" not in blob


@pytest.mark.asyncio
async def test_user_story_cannot_become_cover_and_publication_keeps_cover(
    client: TestClient,
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    from app.db.models import CheckIn, UserDevice

    headers = auth_headers(client, persona="alpha")
    venue_id, org_id, _ = await _link_venue(client, db_session, headers)
    owner_id = UUID(me(client, headers)["id"])
    owner = await db_session.get(User, owner_id)
    assert owner is not None

    cover_asset = await insert_venue_owned_media(
        db_session,
        venue_id=venue_id,
        organization_id=UUID(org_id),
        owner_user_id=owner_id,
    )
    set_cover = client.put(
        f"/v1/venues/{venue_id}/cover",
        headers=_idem(headers),
        json={"media_asset_id": str(cover_asset.id)},
    )
    assert set_cover.status_code == 200, set_cover.text

    # Build a user_story asset at the managed venue (not MediaWorld) so cleanup
    # does not cross venue FK boundaries.
    now = datetime.now(UTC)
    active = await db_session.execute(
        select(CheckIn).where(
            CheckIn.user_id == owner_id,
            CheckIn.state.in_(("provisional", "verified", "rechecking", "degraded")),
        )
    )
    for row in active.scalars().all():
        row.exited_at = now
        row.state = "exited"
        row.exit_reason = "test_cleanup"
    await db_session.flush()

    device = UserDevice(
        user_id=owner_id,
        platform="ios",
        installation_id=uuid4(),
    )
    db_session.add(device)
    await db_session.flush()
    check_in = CheckIn(
        user_id=owner_id,
        venue_id=venue_id,
        state="verified",
        verification_level="standard",
        confidence_score=90,
        entry_method="fused_location",
        ghost_mode_snapshot=False,
        discoverable_snapshot=True,
        entered_at=now - timedelta(minutes=5),
        verified_at=now - timedelta(minutes=5),
        last_verified_at=now - timedelta(minutes=1),
        verified_until=now + timedelta(minutes=10),
        grace_until=now + timedelta(minutes=15),
        lease_expires_at=now + timedelta(minutes=15),
        geofence_version=1,
    )
    db_session.add(check_in)
    await db_session.flush()
    story_asset = MediaAsset(
        owner_user_id=owner_id,
        venue_id=venue_id,
        purpose="user_story",
        organization_id=None,
        author_check_in_id=check_in.id,
        device_id=device.id,
        media_type="image",
        lifecycle_status="ready",
        moderation_status="approved",
        attribution_mode="attributed",
        quarantine_object_key=f"quarantine/u{owner_id}/{uuid4()}/original.jpg",
        declared_mime_type="image/jpeg",
        declared_byte_size=12_345,
        intent_expires_at=now + timedelta(hours=1),
    )
    db_session.add(story_asset)
    await db_session.commit()

    cover = CoverService(db_session, valkey, media_settings)
    with pytest.raises(AppError) as exc:
        await cover.set_cover(owner, venue_id, story_asset.id, now=datetime.now(UTC))
    assert exc.value.code == "COVER_MEDIA_INVALID"

    venue = await db_session.get(Venue, venue_id)
    assert venue is not None
    assert venue.primary_cover_media_id == cover_asset.id

    official = await insert_published_official_story(
        db_session,
        uploader=owner,
        venue_id=venue_id,
        organization_id=UUID(org_id),
    )
    await db_session.refresh(venue)
    assert venue.primary_cover_media_id == cover_asset.id

    service = StoryService(db_session, valkey, media_settings)
    await service.delete_story(user=owner, story_id=official.id, now=datetime.now(UTC))
    await db_session.refresh(venue)
    assert venue.primary_cover_media_id == cover_asset.id


@pytest.mark.asyncio
async def test_official_story_media_never_creates_live_vibe(
    client: TestClient,
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    headers = auth_headers(client, persona="alpha")
    venue_id, org_id, _ = await _link_venue(client, db_session, headers)
    owner = await db_session.get(User, UUID(me(client, headers)["id"]))
    assert owner is not None
    service = StoryService(db_session, valkey, media_settings)
    created = await service.create_official_story_upload(
        user=owner,
        venue_id=venue_id,
        request=CreateOfficialStoryUploadRequest(
            media_type="image",
            mime_type="image/jpeg",
            byte_size=2048,
        ),
        now=datetime.now(UTC),
    )
    vibe_count = await db_session.execute(
        select(func.count())
        .select_from(LiveVibe)
        .where(LiveVibe.media_asset_id == created.media_asset_id)
    )
    assert int(vibe_count.scalar_one()) == 0
    _ = org_id


@pytest.mark.asyncio
async def test_moderation_rejection_and_duplicate_publish(
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    world = await build_world(db_session, valkey, media_settings)
    try:
        now = datetime.now(UTC)
        asset = MediaAsset(
            owner_user_id=world.author_id,
            venue_id=world.venue_id,
            purpose="user_story",
            organization_id=None,
            author_check_in_id=world.check_in_id,
            device_id=world.device_id,
            media_type="image",
            lifecycle_status="ready",
            moderation_status="approved",
            attribution_mode="attributed",
            quarantine_object_key=f"quarantine/u{world.author_id}/{uuid4()}/original.jpg",
            declared_mime_type="image/jpeg",
            declared_byte_size=1000,
            intent_expires_at=now + timedelta(hours=1),
        )
        db_session.add(asset)
        await db_session.flush()
        story = Story(
            venue_id=world.venue_id,
            media_asset_id=asset.id,
            author_type="user",
            author_user_id=world.author_id,
            created_by_user_id=world.author_id,
            attribution_mode="attributed",
            reply_policy="disabled",
            publication_status="processing",
            moderation_status="pending",
            created_at=now,
            updated_at=now,
        )
        db_session.add(story)
        await db_session.commit()

        await reject_content_for_media_asset(db_session, asset.id, now=now)
        await db_session.commit()
        await db_session.refresh(story)
        assert story.publication_status == "rejected"

        # Separate processing path: publish then replay must not double-emit.
        story2_asset = MediaAsset(
            owner_user_id=world.author_id,
            venue_id=world.venue_id,
            purpose="user_story",
            organization_id=None,
            author_check_in_id=world.check_in_id,
            device_id=world.device_id,
            media_type="image",
            lifecycle_status="ready",
            moderation_status="approved",
            attribution_mode="attributed",
            quarantine_object_key=f"quarantine/u{world.author_id}/{uuid4()}/original.jpg",
            declared_mime_type="image/jpeg",
            declared_byte_size=1000,
            intent_expires_at=now + timedelta(hours=1),
        )
        db_session.add(story2_asset)
        await db_session.flush()
        story2 = Story(
            venue_id=world.venue_id,
            media_asset_id=story2_asset.id,
            author_type="user",
            author_user_id=world.author_id,
            created_by_user_id=world.author_id,
            attribution_mode="attributed",
            reply_policy="disabled",
            publication_status="processing",
            moderation_status="pending",
            created_at=now,
            updated_at=now,
        )
        db_session.add(story2)
        await db_session.commit()

        assert await publish_content_for_media_asset(
            db_session, story2_asset.id, now=now, settings=media_settings
        )
        await db_session.commit()
        assert await publish_content_for_media_asset(
            db_session, story2_asset.id, now=now + timedelta(seconds=1), settings=media_settings
        )
        await db_session.commit()

        events = await db_session.execute(
            select(func.count())
            .select_from(OutboxEvent)
            .where(
                OutboxEvent.aggregate_id == story2.id,
                OutboxEvent.event_type == "story.published",
            )
        )
        assert int(events.scalar_one()) == 1
        await db_session.refresh(story2)
        assert story2.expires_at == now + timedelta(hours=media_settings.story_ttl_hours)
    finally:
        await world.cleanup()


@pytest.mark.asyncio
async def test_processing_finishes_after_author_leaves_and_exclusions(
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    world = await build_world(db_session, valkey, media_settings)
    try:
        now = datetime.now(UTC)
        asset = MediaAsset(
            owner_user_id=world.author_id,
            venue_id=world.venue_id,
            purpose="user_story",
            organization_id=None,
            author_check_in_id=world.check_in_id,
            device_id=world.device_id,
            media_type="image",
            lifecycle_status="ready",
            moderation_status="approved",
            attribution_mode="attributed",
            quarantine_object_key=f"quarantine/u{world.author_id}/{uuid4()}/original.jpg",
            declared_mime_type="image/jpeg",
            declared_byte_size=1000,
            intent_expires_at=now + timedelta(hours=1),
        )
        db_session.add(asset)
        await db_session.flush()
        story = Story(
            venue_id=world.venue_id,
            media_asset_id=asset.id,
            author_type="user",
            author_user_id=world.author_id,
            created_by_user_id=world.author_id,
            attribution_mode="attributed",
            reply_policy="disabled",
            publication_status="processing",
            moderation_status="pending",
            created_at=now,
            updated_at=now,
        )
        db_session.add(story)
        await db_session.commit()

        await world.clear_lease()
        assert await publish_content_for_media_asset(
            db_session, asset.id, now=now, settings=media_settings
        )
        await db_session.commit()
        await db_session.refresh(story)
        assert story.publication_status == "published"

        service = StoryService(db_session, valkey, media_settings)
        # Exclude non-public statuses from experience feed.
        hidden = await insert_published_user_story(
            db_session,
            user=world.author,
            venue_id=world.venue_id,
            check_in_id=world.check_in_id,
            device_id=world.device_id,
            now=now,
        )
        hidden.publication_status = "hidden"
        rejected = await insert_published_user_story(
            db_session,
            user=world.author,
            venue_id=world.venue_id,
            check_in_id=world.check_in_id,
            device_id=world.device_id,
            now=now,
        )
        mark_rejected(rejected, now=now)
        deleted = await insert_published_user_story(
            db_session,
            user=world.author,
            venue_id=world.venue_id,
            check_in_id=world.check_in_id,
            device_id=world.device_id,
            now=now,
        )
        mark_deleted(deleted, now=now)
        processing_asset = MediaAsset(
            owner_user_id=world.author_id,
            venue_id=world.venue_id,
            purpose="user_story",
            organization_id=None,
            author_check_in_id=world.check_in_id,
            device_id=world.device_id,
            media_type="image",
            lifecycle_status="processing",
            moderation_status="pending",
            attribution_mode="attributed",
            quarantine_object_key=f"quarantine/u{world.author_id}/{uuid4()}/original.jpg",
            declared_mime_type="image/jpeg",
            declared_byte_size=1000,
            intent_expires_at=now + timedelta(hours=1),
        )
        db_session.add(processing_asset)
        await db_session.flush()
        processing = Story(
            venue_id=world.venue_id,
            media_asset_id=processing_asset.id,
            author_type="user",
            author_user_id=world.author_id,
            created_by_user_id=world.author_id,
            attribution_mode="attributed",
            reply_policy="disabled",
            publication_status="processing",
            moderation_status="pending",
            created_at=now,
            updated_at=now,
        )
        db_session.add(processing)
        await db_session.commit()

        groups = await service.list_experience_story_groups(viewer=world.viewer, now=now)
        ids = {
            slide.story_id
            for g in groups.items
            for slide in (
                await service.get_story_group(viewer=world.viewer, group_key=g.group_key, now=now)
            ).slides
        }
        assert story.id in ids
        assert hidden.id not in ids
        assert rejected.id not in ids
        assert deleted.id not in ids
        assert processing.id not in ids
    finally:
        await world.cleanup()


@pytest.mark.asyncio
async def test_moderation_provider_failure_fails_closed_for_story(
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    """Provider failure maps to manual_review and must not publish Stories."""
    from app.modules.media.moderation import ModerationResult, ModerationSignalResult
    from app.modules.media.pipeline import MediaPipeline
    from app.modules.stories.lifecycle import is_publicly_viewable

    world = await build_world(db_session, valkey, media_settings)
    try:
        now = datetime.now(UTC)
        asset = MediaAsset(
            owner_user_id=world.author_id,
            venue_id=world.venue_id,
            purpose="user_story",
            organization_id=None,
            author_check_in_id=world.check_in_id,
            device_id=world.device_id,
            media_type="image",
            lifecycle_status="moderation_pending",
            moderation_status="pending",
            attribution_mode="attributed",
            quarantine_object_key=f"quarantine/u{world.author_id}/{uuid4()}/original.jpg",
            declared_mime_type="image/jpeg",
            declared_byte_size=1000,
            intent_expires_at=now + timedelta(hours=1),
        )
        db_session.add(asset)
        await db_session.flush()
        story = Story(
            venue_id=world.venue_id,
            media_asset_id=asset.id,
            author_type="user",
            author_user_id=world.author_id,
            created_by_user_id=world.author_id,
            attribution_mode="attributed",
            reply_policy="disabled",
            publication_status="processing",
            moderation_status="pending",
            created_at=now,
            updated_at=now,
        )
        db_session.add(story)
        await db_session.commit()

        pipeline = MediaPipeline(db_session, media_settings)
        result = ModerationResult(
            decision="manual_review",
            provider="exploding",
            policy_version=media_settings.media_moderation_policy_version,
            signals=[ModerationSignalResult(category="provider_error", confidence=None)],
        )
        await pipeline._apply_moderation(asset.id, result=result, now=now)
        await db_session.refresh(asset)
        await db_session.refresh(story)
        assert asset.moderation_status == "manual_review"
        assert story.publication_status == "processing"
        assert not is_publicly_viewable(story, now=now)
    finally:
        await world.cleanup()


@pytest.mark.asyncio
async def test_presence_rechecked_at_completion(
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    world = await build_world(db_session, valkey, media_settings)
    try:
        await world.grant_lease()
        service = StoryService(db_session, valkey, media_settings)
        created = await service.create_user_story_upload(
            user=world.author,
            request=CreateUserStoryUploadRequest(
                venue_id=world.venue_id,
                device_id=world.device_id,
                media_type="image",
                mime_type="image/jpeg",
                byte_size=2048,
                attribution_mode="attributed",
            ),
            now=datetime.now(UTC),
        )
        await world.clear_lease()
        with pytest.raises(AppError) as exc:
            await service.complete_user_story_upload(
                user=world.author,
                upload_id=created.upload_id,
                request=CompleteStoryUploadRequest(device_id=world.device_id),
                now=datetime.now(UTC),
            )
        assert exc.value.code == "STORY_POSTING_NOT_AUTHORIZED"
    finally:
        await world.cleanup()
