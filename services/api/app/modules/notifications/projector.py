"""Idempotent outbox → notification projection (Phase 9A)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import (
    AuthIdentity,
    CallingCard,
    Notification,
    NotificationEventConsumption,
    NotificationPreference,
    OutboxEvent,
    Story,
    User,
    VenueClaim,
)
from app.modules.messaging.authz import MessagingAuthorizer
from app.modules.notifications.constants import (
    CATEGORY_DEFAULTS,
    SOURCE_EVENT_TYPES,
    category_for_type,
)
from app.modules.notifications.deep_links import (
    calling_card_link,
    conversation_link,
    experience_link,
    organization_invitation_link,
    story_link,
    venue_claim_link,
)
from app.modules.notifications.push import create_deliveries_for_notification
from app.modules.notifications.realtime_publish import publish_notification_hint


def _uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _as_dt(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return fallback
    return fallback


async def _actor_label(session: AsyncSession, user_id: UUID | None) -> str:
    if user_id is None:
        return "Someone"
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None or user.account_status == "deleted":
        return "Someone"
    name = (user.display_name or "").strip()
    if name:
        return name
    handle = (user.handle or "").strip()
    return handle or "Someone"


async def _in_app_enabled(session: AsyncSession, user_id: UUID, category: str) -> bool:
    pref = await session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user_id,
            NotificationPreference.category == category,
        )
    )
    if pref is None:
        return CATEGORY_DEFAULTS[category]["in_app_enabled"]
    return bool(pref.in_app_enabled)


async def _mark_consumed(
    session: AsyncSession,
    *,
    event_id: UUID,
    notification_id: UUID | None,
    now: datetime,
) -> bool:
    """Return True if this event was newly consumed; False if already seen."""
    stmt = (
        pg_insert(NotificationEventConsumption)
        .values(event_id=event_id, notification_id=notification_id, consumed_at=now)
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(NotificationEventConsumption.event_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _upsert_simple(
    session: AsyncSession,
    *,
    dedupe_key: str,
    recipient_user_id: UUID,
    notification_type: str,
    title: str,
    body: str,
    deep_link: str | None,
    actor_user_id: UUID | None,
    now: datetime,
    occurred_at: datetime,
    priority: str = "normal",
    venue_id: UUID | None = None,
    conversation_id: UUID | None = None,
    calling_card_id: UUID | None = None,
    story_id: UUID | None = None,
    organization_id: UUID | None = None,
    venue_claim_id: UUID | None = None,
    grouping_key: str | None = None,
    expires_at: datetime | None = None,
) -> tuple[Notification, bool]:
    existing = await session.scalar(
        select(Notification).where(Notification.dedupe_key == dedupe_key).with_for_update()
    )
    if existing is not None:
        existing.title = title
        existing.body = body
        existing.deep_link = deep_link
        existing.latest_event_at = max(existing.latest_event_at, occurred_at)
        existing.updated_at = now
        if actor_user_id is not None:
            existing.actor_user_id = actor_user_id
        return existing, False

    row = Notification(
        recipient_user_id=recipient_user_id,
        notification_type=notification_type,
        actor_user_id=actor_user_id,
        venue_id=venue_id,
        conversation_id=conversation_id,
        calling_card_id=calling_card_id,
        story_id=story_id,
        organization_id=organization_id,
        venue_claim_id=venue_claim_id,
        title=title,
        body=body,
        deep_link=deep_link,
        grouping_key=grouping_key,
        dedupe_key=dedupe_key,
        occurrence_count=1,
        priority=priority,
        expires_at=expires_at,
        latest_event_at=occurred_at,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row, True


async def _coalesce_message(
    session: AsyncSession,
    *,
    recipient_user_id: UUID,
    conversation_id: UUID,
    actor_user_id: UUID,
    actor_name: str,
    now: datetime,
    occurred_at: datetime,
) -> tuple[Notification, bool]:
    grouping_key = f"message:{recipient_user_id}:{conversation_id}"
    dedupe_key = f"message.received:{recipient_user_id}:{conversation_id}"
    title_one = f"New message from {actor_name}"

    # Free a dismissed row's dedupe key so a fresh active notification can form.
    dismissed = await session.scalar(
        select(Notification)
        .where(Notification.dedupe_key == dedupe_key, Notification.dismissed_at.is_not(None))
        .with_for_update()
    )
    if dismissed is not None:
        dismissed.dedupe_key = f"{dedupe_key}:dismissed:{dismissed.id}"
        await session.flush()

    stmt = (
        pg_insert(Notification)
        .values(
            recipient_user_id=recipient_user_id,
            notification_type="message.received",
            actor_user_id=actor_user_id,
            conversation_id=conversation_id,
            title=title_one,
            body=title_one,
            deep_link=conversation_link(conversation_id),
            grouping_key=grouping_key,
            dedupe_key=dedupe_key,
            occurrence_count=1,
            priority="normal",
            latest_event_at=occurred_at,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["dedupe_key"],
            set_={
                "occurrence_count": Notification.occurrence_count + 1,
                "latest_event_at": occurred_at,
                "read_at": None,
                "actor_user_id": actor_user_id,
                "updated_at": now,
            },
        )
        .returning(Notification.id, Notification.occurrence_count)
    )
    row_id, count = (await session.execute(stmt)).one()
    row = await session.get(Notification, row_id)
    assert row is not None
    created = int(count) == 1
    if created:
        row.title = title_one
        row.body = title_one
    else:
        row.title = f"{count} new messages from {actor_name}"
        row.body = f"{count} new messages from {actor_name}"
    row.deep_link = conversation_link(conversation_id)
    row.grouping_key = grouping_key
    await session.flush()
    return row, created


async def _unread_total(session: AsyncSession, user_id: UUID, now: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.recipient_user_id == user_id,
            Notification.read_at.is_(None),
            Notification.dismissed_at.is_(None),
            or_(Notification.expires_at.is_(None), Notification.expires_at > now),
        )
    )
    return int(await session.scalar(stmt) or 0)


async def project_outbox_event(
    session: AsyncSession,
    event: OutboxEvent,
    *,
    redis: Redis[str],
    settings: Settings,
    now: datetime | None = None,
) -> Notification | None:
    """Project a single outbox event. Idempotent via notification_event_consumptions."""
    if event.event_type not in SOURCE_EVENT_TYPES:
        return None

    stamp = now or datetime.now(UTC)
    occurred_at = (
        event.occurred_at if event.occurred_at.tzinfo else event.occurred_at.replace(tzinfo=UTC)
    )
    payload = dict(event.payload or {})

    prior = await session.get(NotificationEventConsumption, event.id)
    if prior is not None:
        if prior.notification_id is None:
            return None
        return await session.get(Notification, prior.notification_id)

    notification: Notification | None = None
    created = False
    hint_type = "notification.created"

    if event.event_type == "calling_card.created":
        card_id = _uuid(payload.get("calling_card_id")) or event.aggregate_id
        recipient_id = _uuid(payload.get("recipient_user_id"))
        sender_id = _uuid(payload.get("sender_user_id"))
        if recipient_id is None or sender_id is None:
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        authz = MessagingAuthorizer(session, settings)
        if await authz.is_blocked(sender_id, recipient_id):
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        if not await _in_app_enabled(session, recipient_id, "calling_cards"):
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        actor_name = await _actor_label(session, sender_id)
        notification, created = await _upsert_simple(
            session,
            dedupe_key=f"calling_card.received:{card_id}",
            recipient_user_id=recipient_id,
            notification_type="calling_card.received",
            title="New Calling Card",
            body=f"{actor_name} sent you a Calling Card",
            deep_link=calling_card_link(card_id),
            actor_user_id=sender_id,
            now=stamp,
            occurred_at=occurred_at,
            priority="high",
            venue_id=_uuid(payload.get("venue_id")),
            calling_card_id=card_id,
            expires_at=_as_dt(payload.get("expires_at"), stamp),
        )

    elif event.event_type == "calling_card.accepted":
        card_id = _uuid(payload.get("calling_card_id")) or event.aggregate_id
        card = await session.get(CallingCard, card_id)
        if card is None:
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        recipient_id = card.sender_user_id
        actor_id = card.recipient_user_id
        authz = MessagingAuthorizer(session, settings)
        if await authz.is_blocked(actor_id, recipient_id):
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        if not await _in_app_enabled(session, recipient_id, "calling_cards"):
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        actor_name = await _actor_label(session, actor_id)
        notification, created = await _upsert_simple(
            session,
            dedupe_key=f"calling_card.accepted:{card_id}",
            recipient_user_id=recipient_id,
            notification_type="calling_card.accepted",
            title="Calling Card accepted",
            body=f"{actor_name} accepted your Calling Card",
            deep_link=calling_card_link(card_id),
            actor_user_id=actor_id,
            now=stamp,
            occurred_at=occurred_at,
            priority="high",
            venue_id=card.venue_id,
            calling_card_id=card_id,
        )

    elif event.event_type == "message.created":
        conversation_id = _uuid(payload.get("conversation_id"))
        sender_id = _uuid(payload.get("sender_user_id"))
        recipients_raw = payload.get("recipient_user_ids")
        recipients: list[Any] = recipients_raw if isinstance(recipients_raw, list) else []
        if conversation_id is None or sender_id is None:
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        other_ids = [
            uid for raw in recipients if (uid := _uuid(raw)) is not None and uid != sender_id
        ]
        if not other_ids:
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        recipient_id = other_ids[0]
        authz = MessagingAuthorizer(session, settings)
        if await authz.is_blocked(sender_id, recipient_id):
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        if not await _in_app_enabled(session, recipient_id, "messages"):
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        actor_name = await _actor_label(session, sender_id)
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:gk))"),
            {"gk": f"message:{recipient_id}:{conversation_id}"},
        )
        notification, created = await _coalesce_message(
            session,
            recipient_user_id=recipient_id,
            conversation_id=conversation_id,
            actor_user_id=sender_id,
            actor_name=actor_name,
            now=stamp,
            occurred_at=occurred_at,
        )
        hint_type = "notification.created" if created else "notification.updated"

    elif event.event_type == "story.published":
        story_id = _uuid(payload.get("story_id")) or event.aggregate_id
        story = await session.get(Story, story_id)
        if story is None or story.created_by_user_id is None:
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        recipient_id = story.created_by_user_id
        if not await _in_app_enabled(session, recipient_id, "stories"):
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        deep = story_link(story_id)
        notification, created = await _upsert_simple(
            session,
            dedupe_key=f"story.published:{story_id}",
            recipient_user_id=recipient_id,
            notification_type="story.published",
            title="Your Story is live",
            body="Your Story was published.",
            deep_link=deep,
            actor_user_id=None,
            now=stamp,
            occurred_at=occurred_at,
            venue_id=story.venue_id,
            story_id=story_id,
            expires_at=story.expires_at,
        )

    elif event.event_type in {"story.rejected", "story.failed"}:
        story_id = _uuid(payload.get("story_id")) or event.aggregate_id
        story = await session.get(Story, story_id)
        if story is None or story.created_by_user_id is None:
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        recipient_id = story.created_by_user_id
        if not await _in_app_enabled(session, recipient_id, "stories"):
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        ntype = "story.rejected" if event.event_type == "story.rejected" else "story.failed"
        title = "Story not published" if ntype == "story.rejected" else "Story processing failed"
        body = (
            "Your Story could not be published."
            if ntype == "story.rejected"
            else "Your Story could not be processed."
        )
        notification, created = await _upsert_simple(
            session,
            dedupe_key=f"{ntype}:{story_id}",
            recipient_user_id=recipient_id,
            notification_type=ntype,
            title=title,
            body=body,
            deep_link=experience_link(),
            actor_user_id=None,
            now=stamp,
            occurred_at=occurred_at,
            priority="high",
            venue_id=story.venue_id,
            story_id=story_id,
        )

    elif event.event_type == "venue.claim.approved":
        claim_id = _uuid(payload.get("claim_id")) or event.aggregate_id
        claimant = _uuid(payload.get("claimant_user_id"))
        if claimant is None:
            claim = await session.get(VenueClaim, claim_id)
            claimant = claim.claimant_user_id if claim else None
        if claimant is None:
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        if not await _in_app_enabled(session, claimant, "venue_management"):
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        notification, created = await _upsert_simple(
            session,
            dedupe_key=f"venue_claim.approved:{claim_id}",
            recipient_user_id=claimant,
            notification_type="venue_claim.approved",
            title="Venue claim approved",
            body="Your venue claim was approved.",
            deep_link=venue_claim_link(claim_id),
            actor_user_id=None,
            now=stamp,
            occurred_at=occurred_at,
            priority="high",
            venue_id=_uuid(payload.get("venue_id")),
            organization_id=_uuid(payload.get("organization_id")),
            venue_claim_id=claim_id,
        )

    elif event.event_type == "venue.claim.rejected":
        claim_id = _uuid(payload.get("claim_id")) or event.aggregate_id
        claimant = _uuid(payload.get("claimant_user_id"))
        if claimant is None:
            claim = await session.get(VenueClaim, claim_id)
            claimant = claim.claimant_user_id if claim else None
        if claimant is None:
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        if not await _in_app_enabled(session, claimant, "venue_management"):
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        notification, created = await _upsert_simple(
            session,
            dedupe_key=f"venue_claim.rejected:{claim_id}",
            recipient_user_id=claimant,
            notification_type="venue_claim.rejected",
            title="Venue claim rejected",
            body="Your venue claim was not approved.",
            deep_link=venue_claim_link(claim_id),
            actor_user_id=None,
            now=stamp,
            occurred_at=occurred_at,
            priority="high",
            venue_id=_uuid(payload.get("venue_id")),
            organization_id=_uuid(payload.get("organization_id")),
            venue_claim_id=claim_id,
        )

    elif event.event_type == "organization.invitation.created":
        invitation_id = _uuid(payload.get("invitation_id")) or event.aggregate_id
        email = str(payload.get("email_normalized") or "").strip().lower()
        org_id = _uuid(payload.get("organization_id"))
        _ = org_id
        if not email:
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        identity = await session.scalar(
            select(AuthIdentity).where(AuthIdentity.normalized_email == email).limit(1)
        )
        if identity is None:
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        recipient_id = identity.user_id
        if not await _in_app_enabled(session, recipient_id, "venue_management"):
            await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
            return None
        notification, created = await _upsert_simple(
            session,
            dedupe_key=f"organization.invitation.received:{invitation_id}",
            recipient_user_id=recipient_id,
            notification_type="organization.invitation.received",
            title="Organization invitation",
            body="You have been invited to join an organization.",
            deep_link=organization_invitation_link(invitation_id),
            actor_user_id=None,
            now=stamp,
            occurred_at=occurred_at,
            priority="high",
            organization_id=None,
            expires_at=_as_dt(payload.get("expires_at"), stamp),
        )

    else:
        await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
        return None

    if notification is None:
        await _mark_consumed(session, event_id=event.id, notification_id=None, now=stamp)
        return None

    newly = await _mark_consumed(
        session, event_id=event.id, notification_id=notification.id, now=stamp
    )
    if not newly:
        return notification

    await create_deliveries_for_notification(session, notification, now=stamp)
    await session.flush()

    if created:
        hint_type = "notification.created"
    elif hint_type != "notification.updated":
        hint_type = "notification.updated"

    unread_total = await _unread_total(session, notification.recipient_user_id, stamp)
    await publish_notification_hint(
        redis,
        user_id=notification.recipient_user_id,
        event_type=hint_type,
        payload={
            "notification_id": str(notification.id),
            "notification_type": notification.notification_type,
            "category": category_for_type(notification.notification_type),
            "occurrence_count": notification.occurrence_count,
            "deep_link": notification.deep_link,
            "latest_event_at": notification.latest_event_at.isoformat(),
        },
    )
    await publish_notification_hint(
        redis,
        user_id=notification.recipient_user_id,
        event_type="unread_count.changed",
        payload={"total": unread_total},
    )
    return notification
