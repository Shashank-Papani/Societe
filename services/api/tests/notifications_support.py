"""Helpers for Phase 9A notification tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from calling_cards_support import CallingCardWorld
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Notification, NotificationDelivery, OutboxEvent, UserDevice
from app.modules.notifications.projector import project_outbox_event
from app.modules.notifications.service import NotificationService


def notification_service(world: CallingCardWorld) -> NotificationService:
    return NotificationService(world.session, world.redis, world.settings)


async def project_pending(
    world: CallingCardWorld, *, event_types: set[str] | None = None
) -> list[Notification]:
    stmt = select(OutboxEvent).where(OutboxEvent.published_at.is_(None))
    if event_types is not None:
        stmt = stmt.where(OutboxEvent.event_type.in_(event_types))
    events = list((await world.session.execute(stmt)).scalars().all())
    created: list[Notification] = []
    now = datetime.now(UTC)
    for event in events:
        row = await project_outbox_event(
            world.session,
            event,
            redis=world.redis,
            settings=world.settings,
            now=now,
        )
        if row is not None:
            created.append(row)
        event.published_at = now
    await world.session.commit()
    return created


async def notifications_for(session: AsyncSession, user_id: UUID) -> list[Notification]:
    result = await session.execute(
        select(Notification)
        .where(Notification.recipient_user_id == user_id)
        .order_by(Notification.created_at.asc())
    )
    return list(result.scalars().all())


async def ensure_device(session: AsyncSession, user_id: UUID) -> UserDevice:
    existing = await session.scalar(
        select(UserDevice).where(UserDevice.user_id == user_id, UserDevice.revoked_at.is_(None))
    )
    if existing is not None:
        return existing
    device = UserDevice(
        user_id=user_id,
        platform="ios",
        installation_id=uuid4(),
        app_version="1.0.0",
        os_version="18.0",
    )
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return device


async def deliveries_for(
    session: AsyncSession, notification_id: UUID
) -> list[NotificationDelivery]:
    result = await session.execute(
        select(NotificationDelivery).where(NotificationDelivery.notification_id == notification_id)
    )
    return list(result.scalars().all())
