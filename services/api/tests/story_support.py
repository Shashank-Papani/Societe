"""Helpers for Phase 8A Stories / official-content tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MediaAsset, OfficialVenuePost, Story, User
from app.modules.stories.lifecycle import publish_official_post, publish_story


async def insert_user_story_asset(
    session: AsyncSession,
    *,
    user: User,
    venue_id: UUID,
    check_in_id: UUID,
    device_id: UUID,
    attribution_mode: str = "attributed",
    lifecycle_status: str = "ready",
    moderation_status: str = "approved",
) -> MediaAsset:
    asset = MediaAsset(
        owner_user_id=user.id,
        venue_id=venue_id,
        purpose="user_story",
        organization_id=None,
        author_check_in_id=check_in_id,
        device_id=device_id,
        media_type="image",
        lifecycle_status=lifecycle_status,
        moderation_status=moderation_status,
        attribution_mode=attribution_mode,
        quarantine_object_key=f"quarantine/u{user.id}/{uuid4()}/original.jpg",
        declared_mime_type="image/jpeg",
        declared_byte_size=12_345,
        intent_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(asset)
    await session.flush()
    return asset


async def insert_published_user_story(
    session: AsyncSession,
    *,
    user: User,
    venue_id: UUID,
    check_in_id: UUID,
    device_id: UUID,
    attribution_mode: str = "attributed",
    now: datetime | None = None,
    caption: str | None = "hello",
) -> Story:
    moment = now or datetime.now(UTC)
    asset = await insert_user_story_asset(
        session,
        user=user,
        venue_id=venue_id,
        check_in_id=check_in_id,
        device_id=device_id,
        attribution_mode=attribution_mode,
    )
    story = Story(
        venue_id=venue_id,
        media_asset_id=asset.id,
        author_type="user",
        author_user_id=user.id,
        created_by_user_id=user.id,
        attribution_mode=attribution_mode,
        caption=caption,
        vibe_tags=["nightlife"],
        reply_policy="disabled",
        publication_status="draft",
        moderation_status="pending",
        created_at=moment,
        updated_at=moment,
    )
    session.add(story)
    await session.flush()
    publish_story(story, now=moment)
    await session.commit()
    await session.refresh(story)
    return story


async def insert_published_official_story(
    session: AsyncSession,
    *,
    uploader: User,
    venue_id: UUID,
    organization_id: UUID,
    now: datetime | None = None,
) -> Story:
    moment = now or datetime.now(UTC)
    asset = MediaAsset(
        owner_user_id=uploader.id,
        venue_id=venue_id,
        purpose="venue_owned",
        organization_id=organization_id,
        author_check_in_id=None,
        device_id=None,
        media_type="image",
        lifecycle_status="ready",
        moderation_status="approved",
        attribution_mode="attributed",
        quarantine_object_key=f"quarantine/u{uploader.id}/{uuid4()}/original.jpg",
        declared_mime_type="image/jpeg",
        declared_byte_size=12_345,
        intent_expires_at=moment + timedelta(hours=1),
    )
    session.add(asset)
    await session.flush()
    story = Story(
        venue_id=venue_id,
        media_asset_id=asset.id,
        author_type="venue",
        author_user_id=None,
        organization_id=organization_id,
        created_by_user_id=uploader.id,
        attribution_mode="official",
        caption="Tonight",
        vibe_tags=[],
        reply_policy="disabled",
        publication_status="draft",
        moderation_status="pending",
        created_at=moment,
        updated_at=moment,
    )
    session.add(story)
    await session.flush()
    publish_story(story, now=moment)
    await session.commit()
    await session.refresh(story)
    return story


async def insert_text_official_post(
    session: AsyncSession,
    *,
    user: User,
    venue_id: UUID,
    organization_id: UUID,
    now: datetime | None = None,
    body: str = "Doors at 10.",
) -> OfficialVenuePost:
    moment = now or datetime.now(UTC)
    post = OfficialVenuePost(
        venue_id=venue_id,
        organization_id=organization_id,
        created_by_user_id=user.id,
        media_asset_id=None,
        post_type="announcement",
        title="Tonight",
        body=body,
        publication_status="draft",
        moderation_status="pending",
        created_at=moment,
        updated_at=moment,
    )
    session.add(post)
    await session.flush()
    publish_official_post(post, now=moment)
    await session.commit()
    await session.refresh(post)
    return post
