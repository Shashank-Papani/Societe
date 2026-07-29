"""Story views concurrency and report outbox privacy."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from media_support import build_world
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from story_support import insert_published_user_story

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import OutboxEvent, StoryView, User
from app.modules.stories.schemas import CreateStoryReportRequest
from app.modules.stories.service import StoryService


@pytest.mark.asyncio
async def test_views_idempotent_and_reports(
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    world = await build_world(db_session, valkey, media_settings)
    try:
        now = datetime.now(UTC)
        story = await insert_published_user_story(
            db_session,
            user=world.author,
            venue_id=world.venue_id,
            check_in_id=world.check_in_id,
            device_id=world.device_id,
            now=now,
        )
        service = StoryService(db_session, valkey, media_settings)

        view = await service.record_view(viewer=world.viewer, story_id=story.id, now=now)
        assert view.viewed is True
        again = await service.record_view(viewer=world.viewer, story_id=story.id, now=now)
        assert again.viewed is True

        count = await db_session.execute(
            select(func.count())
            .select_from(StoryView)
            .where(
                StoryView.story_id == story.id,
                StoryView.viewer_user_id == world.viewer_id,
            )
        )
        assert int(count.scalar_one()) == 1

        with pytest.raises(AppError) as own:
            await service.report_story(
                reporter=world.author,
                story_id=story.id,
                request=CreateStoryReportRequest(reason="spam"),
                now=now,
            )
        assert own.value.code == "CANNOT_REPORT_OWN_CONTENT"

        report = await service.report_story(
            reporter=world.viewer,
            story_id=story.id,
            request=CreateStoryReportRequest(
                reason="spam",
                description="contains private notes and identity",
            ),
            now=now,
        )
        assert report.status == "open"

        events = await db_session.execute(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == story.id,
                OutboxEvent.event_type == "story.reported",
            )
        )
        event = events.scalar_one()
        payload = event.payload
        assert payload["reason"] == "spam"
        assert "description" not in payload
        assert "reporter_user_id" not in payload
        assert "handle" not in str(payload)
        assert str(world.viewer_id) not in str(payload)

        with pytest.raises(AppError) as dup:
            await service.report_story(
                reporter=world.viewer,
                story_id=story.id,
                request=CreateStoryReportRequest(reason="spam"),
                now=now + timedelta(seconds=1),
            )
        assert dup.value.code == "STORY_REPORT_DUPLICATE"
    finally:
        await world.cleanup()


@pytest.mark.asyncio
async def test_concurrent_story_views_create_one_row(
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    world = await build_world(db_session, valkey, media_settings)
    try:
        now = datetime.now(UTC)
        story = await insert_published_user_story(
            db_session,
            user=world.author,
            venue_id=world.venue_id,
            check_in_id=world.check_in_id,
            device_id=world.device_id,
            now=now,
        )
        story_id = story.id
        viewer_id = world.viewer_id

        engine = create_async_engine(media_settings.database_url, poolclass=NullPool)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def _record() -> None:
            async with factory() as session:
                service = StoryService(session, valkey, media_settings)
                viewer = await session.get(User, viewer_id)
                assert viewer is not None
                await service.record_view(viewer=viewer, story_id=story_id, now=now)

        await asyncio.gather(_record(), _record(), _record())
        await engine.dispose()

        count = await db_session.execute(
            select(func.count())
            .select_from(StoryView)
            .where(
                StoryView.story_id == story_id,
                StoryView.viewer_user_id == viewer_id,
            )
        )
        assert int(count.scalar_one()) == 1
    finally:
        await world.cleanup()
