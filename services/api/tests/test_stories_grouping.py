"""Story lifecycle, grouping helpers, schema constraints, and experience privacy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from media_support import build_world
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from story_support import insert_published_user_story

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.stories.grouping import (
    logical_group_id,
    sign_group_key,
    verify_group_key,
)
from app.modules.stories.lifecycle import (
    STORY_PUBLIC_WINDOW,
    expire_story,
    is_publicly_viewable,
    mark_deleted,
    publish_story,
    start_processing,
)
from app.modules.stories.official_posts import validate_cta_url
from app.modules.stories.schemas import (
    CreateOfficialPostRequest,
    CreateUserStoryUploadRequest,
)
from app.modules.stories.service import StoryService


class _Story:
    def __init__(self) -> None:
        self.id = uuid4()
        self.publication_status = "draft"
        self.moderation_status = "pending"
        self.published_at = None
        self.expires_at = None
        self.deleted_at = None
        self.updated_at = datetime.now(UTC)


def test_publish_story_sets_24h_window() -> None:
    story = _Story()
    now = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)
    expires = publish_story(story, now=now)  # type: ignore[arg-type]
    assert story.publication_status == "published"
    assert story.moderation_status == "approved"
    assert story.published_at == now
    assert expires == now + STORY_PUBLIC_WINDOW
    assert is_publicly_viewable(story, now=now)  # type: ignore[arg-type]
    assert not is_publicly_viewable(story, now=expires)  # type: ignore[arg-type]


def test_story_transitions_and_delete() -> None:
    story = _Story()
    now = datetime.now(UTC)
    start_processing(story, now=now)  # type: ignore[arg-type]
    publish_story(story, now=now)  # type: ignore[arg-type]
    expire_story(story, now=now + timedelta(hours=25))  # type: ignore[arg-type]
    assert story.publication_status == "expired"
    mark_deleted(story, now=now + timedelta(hours=26))  # type: ignore[arg-type]
    assert story.publication_status == "deleted"
    assert story.deleted_at is not None


def test_group_key_roundtrip() -> None:
    secret = "test-cursor-hmac-secret-0123456789abcdef01234567"
    logical = logical_group_id(
        author_type="user",
        attribution_mode="attributed",
        venue_id=uuid4(),
        author_user_id=uuid4(),
        story_id=uuid4(),
    )
    key = sign_group_key(logical_id=logical, secret=secret)
    verified = verify_group_key(group_key=key, secret=secret)
    assert verified["logical_id"] == logical
    assert verified["group_type"] == "user"


def test_anonymous_group_is_per_story() -> None:
    venue = uuid4()
    a = logical_group_id(
        author_type="user",
        attribution_mode="anonymous",
        venue_id=venue,
        author_user_id=uuid4(),
        story_id=uuid4(),
    )
    b = logical_group_id(
        author_type="user",
        attribution_mode="anonymous",
        venue_id=venue,
        author_user_id=uuid4(),
        story_id=uuid4(),
    )
    assert a != b
    assert a.startswith("anon:")


def test_cta_url_https_only() -> None:
    assert validate_cta_url("https://example.com/tickets") == "https://example.com/tickets"
    with pytest.raises(AppError) as exc:
        validate_cta_url("http://example.com")
    assert exc.value.code == "OFFICIAL_POST_CTA_INVALID"


def test_user_story_schema_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        CreateUserStoryUploadRequest(
            venue_id=uuid4(),
            device_id=uuid4(),
            media_type="image",
            mime_type="image/jpeg",
            byte_size=100,
            attribution_mode="attributed",
            extra_field="nope",  # type: ignore[call-arg]
        )


def test_official_post_media_fields_together() -> None:
    with pytest.raises(ValidationError):
        CreateOfficialPostRequest(
            post_type="announcement",
            body="Hello",
            media_type="image",
        )


@pytest.mark.asyncio
async def test_experience_grouping_anonymous_privacy_and_unviewed_sort(
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    world = await build_world(db_session, valkey, media_settings)
    try:
        now = datetime.now(UTC)
        attributed_story = await insert_published_user_story(
            db_session,
            user=world.author,
            venue_id=world.venue_id,
            check_in_id=world.check_in_id,
            device_id=world.device_id,
            attribution_mode="attributed",
            now=now - timedelta(minutes=5),
        )
        anonymous = await insert_published_user_story(
            db_session,
            user=world.author,
            venue_id=world.venue_id,
            check_in_id=world.check_in_id,
            device_id=world.device_id,
            attribution_mode="anonymous",
            now=now - timedelta(minutes=1),
        )
        service = StoryService(db_session, valkey, media_settings)
        await service.record_view(viewer=world.viewer, story_id=attributed_story.id, now=now)

        groups = await service.list_experience_story_groups(viewer=world.viewer, now=now)
        assert groups.items[0].group_type == "anon"
        assert groups.items[0].author is None
        assert groups.items[0].author_label == "Anonymous"
        assert groups.items[0].unviewed_count >= 1

        anon_detail = await service.get_story_group(
            viewer=world.viewer, group_key=groups.items[0].group_key, now=now
        )
        assert anon_detail.slides[0].story_id == anonymous.id
        assert anon_detail.slides[0].author is None
        assert anon_detail.slides[0].is_mine is False

        mine = await service.get_story_group(
            viewer=world.author, group_key=groups.items[0].group_key, now=now
        )
        assert mine.slides[0].is_mine is True
        assert mine.slides[0].author is None
    finally:
        await world.cleanup()
