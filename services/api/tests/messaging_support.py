"""Helpers for private messaging tests built on Calling Card worlds."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from calling_cards_support import CallingCardWorld
from sqlalchemy import select

from app.db.models import ConnectionGrant, OutboxEvent
from app.modules.messaging.service import MessagingService
from app.modules.social.schemas import CreateCallingCardRequest, RespondCallingCardRequest


async def accept_connection(
    world: CallingCardWorld, *, now: datetime | None = None
) -> ConnectionGrant:
    moment = now or datetime.now(UTC)
    await world.grant_both_verified(now=moment)
    service = world.service()
    created = await service.create_calling_card(
        user=world.sender,
        request=CreateCallingCardRequest(recipient_user_id=world.recipient_id),
        idempotency_key=str(uuid4()),
        now=moment,
    )
    await service.respond(
        user=world.recipient,
        calling_card_id=created.id,
        request=RespondCallingCardRequest(decision="accept", action="accept_only"),
        now=moment,
    )
    result = await world.session.execute(
        select(ConnectionGrant).where(ConnectionGrant.calling_card_id == created.id)
    )
    grant = result.scalar_one()
    assert grant.expires_at is None
    assert grant.revoked_at is None
    return grant


def messaging_service(world: CallingCardWorld) -> MessagingService:
    return MessagingService(world.session, world.redis, world.settings)


async def outbox_of_type(world: CallingCardWorld, event_type: str) -> list[OutboxEvent]:
    result = await world.session.execute(
        select(OutboxEvent).where(OutboxEvent.event_type == event_type)
    )
    return list(result.scalars().all())
