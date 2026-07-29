"""Story expiration (read-time + retention worker)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from media_support import build_world
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from story_support import insert_published_user_story

from app.core.config import Settings
from app.db.models import LiveVibe, MediaAsset, OutboxEvent, Story
from app.modules.media.retention import MediaRetentionService
from app.modules.stories.lifecycle import is_publicly_viewable
from app.modules.stories.publication import publish_content_for_media_asset


@pytest.mark.asyncio
async def test_story_expiration_read_time_and_worker(
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    world = await build_world(db_session, valkey, media_settings)
    try:
        past = datetime.now(UTC) - timedelta(hours=25)
        story = await insert_published_user_story(
            db_session,
            user=world.author,
            venue_id=world.venue_id,
            check_in_id=world.check_in_id,
            device_id=world.device_id,
            now=past,
        )
        assert story.expires_at is not None
        assert story.expires_at < datetime.now(UTC)
        assert not is_publicly_viewable(story, now=datetime.now(UTC))

        retention = MediaRetentionService(db_session, media_settings)
        expired = await retention.expire_due_stories(now=datetime.now(UTC))
        assert expired >= 1
        await db_session.refresh(story)
        assert story.publication_status == "expired"

        events = await db_session.execute(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == story.id,
                OutboxEvent.event_type == "story.expired",
            )
        )
        assert events.scalar_one_or_none() is not None
    finally:
        await world.cleanup()


@pytest.mark.asyncio
async def test_publish_after_moderation_approval_for_story(
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

        handled = await publish_content_for_media_asset(
            db_session, asset.id, now=now, settings=media_settings
        )
        assert handled is True
        await db_session.commit()
        await db_session.refresh(story)
        assert story.publication_status == "published"
        assert story.expires_at == now + timedelta(hours=media_settings.story_ttl_hours)

        vibe = await db_session.execute(select(LiveVibe).where(LiveVibe.media_asset_id == asset.id))
        assert vibe.scalar_one_or_none() is None
    finally:
        await world.cleanup()
