"""Publish Stories / official posts after media moderation approval.

Kept as a thin module so ``media.pipeline`` does not import ``StoryService``
(and its presence/org deps) at module load time.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import OfficialVenuePost, OutboxEvent, Story
from app.modules.organizations.audit import (
    OFFICIAL_POST_PUBLISHED,
    OFFICIAL_STORY_PUBLISHED,
    append_audit_event,
)
from app.modules.stories.lifecycle import (
    mark_rejected,
    publish_official_post,
    publish_story,
    reject_official_post,
)


async def publish_content_for_media_asset(
    session: AsyncSession,
    media_asset_id: UUID,
    *,
    now: datetime,
    settings: Settings,
) -> bool:
    """Publish a Story or OfficialVenuePost linked to this media asset.

    Returns True when a content object was found and handled.
    """
    story = await session.execute(
        select(Story).where(Story.media_asset_id == media_asset_id).with_for_update()
    )
    story_row = story.scalar_one_or_none()
    if story_row is not None:
        if story_row.publication_status == "published":
            return True
        expires_at = publish_story(
            story_row, now=now, ttl=timedelta(hours=settings.story_ttl_hours)
        )
        event_type = (
            "official_story.published" if story_row.author_type == "venue" else "story.published"
        )
        session.add(
            OutboxEvent(
                aggregate_type="story",
                aggregate_id=story_row.id,
                event_type=event_type,
                payload={
                    "story_id": str(story_row.id),
                    "venue_id": str(story_row.venue_id),
                    "media_asset_id": str(media_asset_id),
                    "author_type": story_row.author_type,
                    "attribution_mode": story_row.attribution_mode,
                    "published_at": now.isoformat(),
                    "expires_at": expires_at.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        if story_row.author_type == "venue" and story_row.organization_id is not None:
            await append_audit_event(
                session,
                event_type=OFFICIAL_STORY_PUBLISHED,
                actor_user_id=story_row.created_by_user_id,
                organization_id=story_row.organization_id,
                venue_id=story_row.venue_id,
                target_type="story",
                target_id=story_row.id,
                metadata={"story_id": str(story_row.id), "media_asset_id": str(media_asset_id)},
            )
        return True

    post = await session.execute(
        select(OfficialVenuePost)
        .where(OfficialVenuePost.media_asset_id == media_asset_id)
        .with_for_update()
    )
    post_row = post.scalar_one_or_none()
    if post_row is None:
        return False
    if post_row.publication_status == "published":
        return True
    publish_official_post(post_row, now=now)
    session.add(
        OutboxEvent(
            aggregate_type="official_venue_post",
            aggregate_id=post_row.id,
            event_type="official_post.published",
            payload={
                "post_id": str(post_row.id),
                "venue_id": str(post_row.venue_id),
                "media_asset_id": str(media_asset_id),
                "published_at": now.isoformat(),
            },
            occurred_at=now,
            available_at=now,
        )
    )
    await append_audit_event(
        session,
        event_type=OFFICIAL_POST_PUBLISHED,
        actor_user_id=post_row.created_by_user_id,
        organization_id=post_row.organization_id,
        venue_id=post_row.venue_id,
        target_type="official_venue_post",
        target_id=post_row.id,
        metadata={"post_id": str(post_row.id), "media_asset_id": str(media_asset_id)},
    )
    return True


async def reject_content_for_media_asset(
    session: AsyncSession,
    media_asset_id: UUID,
    *,
    now: datetime,
) -> bool:
    story = await session.execute(
        select(Story).where(Story.media_asset_id == media_asset_id).with_for_update()
    )
    story_row = story.scalar_one_or_none()
    if story_row is not None:
        if story_row.publication_status not in {"rejected", "deleted"}:
            mark_rejected(story_row, now=now)
            session.add(
                OutboxEvent(
                    aggregate_type="story",
                    aggregate_id=story_row.id,
                    event_type="story.rejected",
                    payload={
                        "story_id": str(story_row.id),
                        "venue_id": str(story_row.venue_id),
                        "media_asset_id": str(media_asset_id),
                        "author_type": story_row.author_type,
                        "rejected_at": now.isoformat(),
                    },
                    occurred_at=now,
                    available_at=now,
                )
            )
        return True

    post = await session.execute(
        select(OfficialVenuePost)
        .where(OfficialVenuePost.media_asset_id == media_asset_id)
        .with_for_update()
    )
    post_row = post.scalar_one_or_none()
    if post_row is None:
        return False
    if post_row.publication_status not in {"rejected", "deleted"}:
        reject_official_post(post_row, now=now)
    return True
