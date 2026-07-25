"""Helpers for Calling Card integration tests against real Postgres + Valkey."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from media_support import BOUNDARY_WKT, CENTROID_WKT, INSERT_VENUE_SQL
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import CheckIn, User, UserPrivacySettings
from app.modules.presence.leases import LeaseWrite, PresenceLeaseStore
from app.modules.social.service import SocialService


@dataclass
class CallingCardWorld:
    session: AsyncSession
    redis: Redis[str]
    settings: Settings
    venue_id: UUID
    other_venue_id: UUID
    timezone: str
    sender: User
    recipient: User
    sender_id: UUID
    recipient_id: UUID
    sender_check_in_id: UUID
    recipient_check_in_id: UUID

    def service(self) -> SocialService:
        return SocialService(self.session, self.redis, self.settings)

    async def set_privacy(
        self,
        user: User,
        *,
        ghost_mode: bool = False,
        discoverable_in_venue: bool = True,
        allow_calling_cards: bool = True,
    ) -> None:
        privacy = user.privacy
        if privacy is None:
            privacy = UserPrivacySettings(user_id=user.id)
            self.session.add(privacy)
            user.privacy = privacy
        privacy.ghost_mode = ghost_mode
        privacy.discoverable_in_venue = discoverable_in_venue
        privacy.allow_calling_cards = allow_calling_cards
        await self.session.commit()

    async def grant_lease(
        self,
        user_id: UUID,
        check_in_id: UUID,
        *,
        venue_id: UUID | None = None,
        state: str = "verified",
        ghost_mode: bool = False,
        discoverable: bool = True,
        verified_for: timedelta = timedelta(minutes=2),
        now: datetime | None = None,
    ) -> None:
        moment = now or datetime.now(UTC)
        await PresenceLeaseStore(self.redis).update(
            LeaseWrite(
                user_id=user_id,
                venue_id=venue_id or self.venue_id,
                check_in_id=check_in_id,
                state=state,
                confidence=92,
                verification_level="standard",
                ghost_mode=ghost_mode,
                discoverable=discoverable,
                verified_until=moment + verified_for,
                grace_until=moment + verified_for + timedelta(minutes=5),
                lease_version=1,
            )
        )

    async def grant_both_verified(
        self,
        *,
        now: datetime | None = None,
        verified_for: timedelta = timedelta(minutes=2),
    ) -> None:
        moment = now or datetime.now(UTC)
        await self.grant_lease(
            self.sender_id,
            self.sender_check_in_id,
            now=moment,
            verified_for=verified_for,
        )
        await self.grant_lease(
            self.recipient_id,
            self.recipient_check_in_id,
            now=moment,
            verified_for=verified_for,
        )

    async def move_sender_to_other_venue(self, *, now: datetime | None = None) -> UUID:
        """Exit the sender's active check-in and open one at ``other_venue_id``."""
        moment = now or datetime.now(UTC)
        result = await self.session.execute(
            text(
                """
                UPDATE app.check_ins
                SET state = 'exited', exited_at = :now, exit_reason = 'test_move',
                    updated_at = :now
                WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": str(self.sender_check_in_id), "now": moment},
        )
        del result
        other = CheckIn(
            user_id=self.sender_id,
            venue_id=self.other_venue_id,
            state="verified",
            verification_level="standard",
            confidence_score=92,
            entry_method="fused_location",
            ghost_mode_snapshot=False,
            discoverable_snapshot=True,
            entered_at=moment - timedelta(minutes=5),
            verified_at=moment - timedelta(minutes=5),
            last_verified_at=moment,
            verified_until=moment + timedelta(minutes=5),
            grace_until=moment + timedelta(minutes=10),
            lease_expires_at=moment + timedelta(minutes=10),
            geofence_version=1,
        )
        self.session.add(other)
        await self.session.commit()
        await self.grant_lease(
            self.sender_id,
            other.id,
            venue_id=self.other_venue_id,
            now=moment,
        )
        return other.id

    async def clear_leases(self) -> None:
        store = PresenceLeaseStore(self.redis)
        await store.clear(self.sender_id, venue_id=self.venue_id)
        await store.clear(self.recipient_id, venue_id=self.venue_id)
        await store.clear(self.sender_id, venue_id=self.other_venue_id)

    async def cleanup(self) -> None:
        await self.session.rollback()
        venue_ids = [str(self.venue_id), str(self.other_venue_id)]
        user_ids = [str(self.sender_id), str(self.recipient_id)]
        await self.session.execute(
            text(
                """
                DELETE FROM app.outbox_events
                WHERE aggregate_id IN (
                    SELECT id FROM app.calling_cards
                    WHERE venue_id = ANY(CAST(:venues AS uuid[]))
                    UNION ALL
                    SELECT id FROM app.check_ins
                    WHERE venue_id = ANY(CAST(:venues AS uuid[]))
                )
                OR (
                    aggregate_type = 'user_block'
                    AND aggregate_id = ANY(CAST(:users AS uuid[]))
                )
                OR (
                    aggregate_type IN ('conversation', 'message')
                    AND aggregate_id IN (
                        SELECT id FROM app.conversations
                        WHERE user_low_id = ANY(CAST(:users AS uuid[]))
                           OR user_high_id = ANY(CAST(:users AS uuid[]))
                        UNION ALL
                        SELECT id FROM app.messages
                        WHERE sender_user_id = ANY(CAST(:users AS uuid[]))
                    )
                )
                """
            ),
            {"venues": venue_ids, "users": user_ids},
        )
        for statement in (
            """
            DELETE FROM app.conversation_members
            WHERE user_id = ANY(CAST(:users AS uuid[]))
            """,
            """
            DELETE FROM app.messages
            WHERE conversation_id IN (
                SELECT id FROM app.conversations
                WHERE user_low_id = ANY(CAST(:users AS uuid[]))
                   OR user_high_id = ANY(CAST(:users AS uuid[]))
            )
            """,
            """
            DELETE FROM app.conversations
            WHERE user_low_id = ANY(CAST(:users AS uuid[]))
               OR user_high_id = ANY(CAST(:users AS uuid[]))
            """,
            """
            DELETE FROM app.connection_grants
            WHERE calling_card_id IN (
                SELECT id FROM app.calling_cards
                WHERE venue_id = ANY(CAST(:venues AS uuid[]))
            )
            """,
            "DELETE FROM app.calling_cards WHERE venue_id = ANY(CAST(:venues AS uuid[]))",
            """
            DELETE FROM app.user_blocks
            WHERE blocker_user_id = ANY(CAST(:users AS uuid[]))
               OR blocked_user_id = ANY(CAST(:users AS uuid[]))
            """,
            "DELETE FROM app.check_ins WHERE venue_id = ANY(CAST(:venues AS uuid[]))",
            "DELETE FROM app.venues WHERE id = ANY(CAST(:venues AS uuid[]))",
        ):
            await self.session.execute(
                text(statement),
                {"venues": venue_ids, "users": user_ids},
            )
        await self.session.execute(
            text("DELETE FROM app.users WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": user_ids},
        )
        await self.session.commit()
        await self.clear_leases()


async def build_calling_card_world(
    session: AsyncSession,
    redis: Redis[str],
    settings: Settings,
    *,
    timezone: str = "America/Los_Angeles",
) -> CallingCardWorld:
    venue_id = uuid4()
    other_venue_id = uuid4()
    suffix = uuid4().hex[:10]
    for vid, slug_prefix, name_prefix in (
        (venue_id, "cc-venue", "CC Venue"),
        (other_venue_id, "cc-other", "CC Other"),
    ):
        await session.execute(
            text(INSERT_VENUE_SQL),
            {
                "id": str(vid),
                "slug": f"{slug_prefix}-{suffix}",
                "name": f"{name_prefix} {suffix}",
                "timezone": timezone,
                "boundary": BOUNDARY_WKT,
                "centroid": CENTROID_WKT,
            },
        )

    sender = User(
        auth_subject=f"cc-sender-{suffix}",
        handle=f"sender_{suffix}",
        display_name="Card Sender",
        account_status="active",
        age_verified=True,
        onboarding_state="completed",
    )
    recipient = User(
        auth_subject=f"cc-recipient-{suffix}",
        handle=f"recipient_{suffix}",
        display_name="Card Recipient",
        account_status="active",
        age_verified=True,
        onboarding_state="completed",
    )
    session.add_all([sender, recipient])
    await session.flush()

    for user in (sender, recipient):
        privacy = UserPrivacySettings(
            user_id=user.id,
            ghost_mode=False,
            discoverable_in_venue=True,
            allow_calling_cards=True,
            allow_messages_from_connections=True,
        )
        session.add(privacy)
        user.privacy = privacy

    entered_at = datetime.now(UTC) - timedelta(minutes=10)
    verified_until = datetime.now(UTC) + timedelta(minutes=5)
    grace_until = verified_until + timedelta(minutes=5)

    def _check_in(user_id: UUID, venue: UUID) -> CheckIn:
        return CheckIn(
            user_id=user_id,
            venue_id=venue,
            state="verified",
            verification_level="standard",
            confidence_score=92,
            entry_method="fused_location",
            ghost_mode_snapshot=False,
            discoverable_snapshot=True,
            entered_at=entered_at,
            verified_at=entered_at,
            last_verified_at=entered_at,
            verified_until=verified_until,
            grace_until=grace_until,
            lease_expires_at=grace_until,
            geofence_version=1,
        )

    sender_ci = _check_in(sender.id, venue_id)
    recipient_ci = _check_in(recipient.id, venue_id)
    session.add_all([sender_ci, recipient_ci])
    await session.commit()

    world = CallingCardWorld(
        session=session,
        redis=redis,
        settings=settings,
        venue_id=venue_id,
        other_venue_id=other_venue_id,
        timezone=timezone,
        sender=sender,
        recipient=recipient,
        sender_id=sender.id,
        recipient_id=recipient.id,
        sender_check_in_id=sender_ci.id,
        recipient_check_in_id=recipient_ci.id,
    )
    await world.grant_both_verified()
    return world
