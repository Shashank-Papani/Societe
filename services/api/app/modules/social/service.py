"""Calling Cards, discovery, and blocks.

REST is authoritative. Outbox rows notify clients to refetch; they never carry
precise location or evidence.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import (
    CallingCard,
    ConnectionGrant,
    OutboxEvent,
    User,
    UserBlock,
    UserPrivacySettings,
)
from app.modules.presence.leases import PresenceLeaseStore, venue_discoverable_key
from app.modules.social.authz import CallingCardAuthorizer, require_calling_cards_enabled
from app.modules.social.lifecycle import (
    CallingCardLifecycleService,
    compute_calling_card_expiry,
    next_venue_night_end,
)
from app.modules.social.schemas import (
    BlockResponse,
    BlockUserRequest,
    CallingCardCreateResponse,
    CallingCardDetailResponse,
    CallingCardListResponse,
    CallingCardStatusResponse,
    CallingCardSummary,
    ConnectionGrantSummary,
    CreateCallingCardRequest,
    DiscoverableUser,
    DiscoverableUsersResponse,
    RespondCallingCardRequest,
    RespondCallingCardResponse,
    ShareCallingCardRequest,
    UnblockResponse,
)

logger = get_logger(__name__)


class SocialService:
    def __init__(self, session: AsyncSession, redis: Redis[str], settings: Settings) -> None:
        self._session = session
        self._redis = redis
        self._settings = settings
        self._authz = CallingCardAuthorizer(session, redis, settings)
        self._leases = PresenceLeaseStore(redis)
        self._lifecycle = CallingCardLifecycleService()

    async def create_calling_card(
        self,
        *,
        user: User,
        request: CreateCallingCardRequest,
        idempotency_key: str,
        now: datetime,
    ) -> CallingCardCreateResponse:
        require_calling_cards_enabled(self._settings)
        existing = await self._load_by_idempotency(user.id, idempotency_key)
        if existing is not None:
            return CallingCardCreateResponse(
                id=existing.id,
                status=existing.status,  # type: ignore[arg-type]
                venue_id=existing.venue_id,
                expires_at=existing.expires_at,
            )

        auth = await self._authz.authorize_send(
            sender=user,
            recipient_user_id=request.recipient_user_id,
            now=now,
        )
        expires_at = compute_calling_card_expiry(now, auth.venue_timezone, self._settings)
        card = CallingCard(
            sender_user_id=user.id,
            recipient_user_id=request.recipient_user_id,
            venue_id=auth.venue_id,
            sender_check_in_id=auth.sender_check_in_id,
            recipient_check_in_id=auth.recipient_check_in_id,
            reason_code=request.reason_code,
            reason_text=request.reason_text,
            status="pending",
            idempotency_key=idempotency_key,
            created_at=now,
            expires_at=expires_at,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(card)
                await self._session.flush()
        except IntegrityError as exc:
            raced = await self._load_by_idempotency(user.id, idempotency_key)
            if raced is not None:
                return CallingCardCreateResponse(
                    id=raced.id,
                    status=raced.status,  # type: ignore[arg-type]
                    venue_id=raced.venue_id,
                    expires_at=raced.expires_at,
                )
            raise AppError(
                "CALLING_CARD_PENDING_EXISTS",
                "A pending Calling Card already exists for this pair.",
                status_code=409,
            ) from exc

        self._emit(
            event_type="calling_card.created",
            card=card,
            actor_user_id=user.id,
            recipient_user_ids=[card.recipient_user_id],
            occurred_at=now,
            payload={
                "calling_card_id": str(card.id),
                "sender_user_id": str(card.sender_user_id),
                "recipient_user_id": str(card.recipient_user_id),
                "venue_id": str(card.venue_id),
                "expires_at": card.expires_at.isoformat(),
                "status": card.status,
            },
        )
        await self._session.commit()
        return CallingCardCreateResponse(
            id=card.id,
            status="pending",
            venue_id=card.venue_id,
            expires_at=card.expires_at,
        )

    async def inbox(self, *, user: User, now: datetime) -> CallingCardListResponse:
        require_calling_cards_enabled(self._settings)
        await self._expire_due_for_user(user.id, now=now)
        result = await self._session.execute(
            select(CallingCard)
            .where(CallingCard.recipient_user_id == user.id)
            .order_by(CallingCard.created_at.desc())
            .limit(50)
        )
        items = [self._summary(card) for card in result.scalars().all()]
        return CallingCardListResponse(items=items)

    async def sent(self, *, user: User, now: datetime) -> CallingCardListResponse:
        require_calling_cards_enabled(self._settings)
        await self._expire_due_for_user(user.id, now=now)
        result = await self._session.execute(
            select(CallingCard)
            .where(CallingCard.sender_user_id == user.id)
            .order_by(CallingCard.created_at.desc())
            .limit(50)
        )
        items = [self._summary(card) for card in result.scalars().all()]
        return CallingCardListResponse(items=items)

    async def detail(
        self, *, user: User, calling_card_id: UUID, now: datetime
    ) -> CallingCardDetailResponse:
        require_calling_cards_enabled(self._settings)
        card = await self._load_visible_card(user, calling_card_id, now=now)
        grant = await self._load_grant(card.id)
        return CallingCardDetailResponse(card=self._summary(card), grant=self._grant_summary(grant))

    async def status(
        self, *, user: User, calling_card_id: UUID, now: datetime
    ) -> CallingCardStatusResponse:
        require_calling_cards_enabled(self._settings)
        card = await self._load_visible_card(user, calling_card_id, now=now)
        return CallingCardStatusResponse(
            id=card.id,
            status=card.status,  # type: ignore[arg-type]
            expires_at=card.expires_at,
            responded_at=card.responded_at,
        )

    async def respond(
        self,
        *,
        user: User,
        calling_card_id: UUID,
        request: RespondCallingCardRequest,
        now: datetime,
    ) -> RespondCallingCardResponse:
        require_calling_cards_enabled(self._settings)
        card = await self._load_card_for_update(calling_card_id)
        if card is None:
            raise AppError("CALLING_CARD_NOT_FOUND", "Calling Card not found.", status_code=404)

        if request.decision == "decline":
            if user.id != card.recipient_user_id:
                raise AppError(
                    "CALLING_CARD_FORBIDDEN",
                    "Only the recipient may respond to this Calling Card.",
                    status_code=403,
                )
            if card.status != "pending":
                raise AppError(
                    "CALLING_CARD_STATE_INVALID",
                    "This Calling Card is no longer pending.",
                    status_code=409,
                    details={"status": card.status},
                )
            self._lifecycle.transition(card, "declined", now=now)
            self._emit(
                event_type="calling_card.declined",
                card=card,
                actor_user_id=user.id,
                recipient_user_ids=[card.sender_user_id],
                occurred_at=now,
                payload={
                    "calling_card_id": str(card.id),
                    "status": card.status,
                },
            )
            await self._session.commit()
            return RespondCallingCardResponse(card=self._summary(card), grant=None)

        if request.action is None:
            raise AppError(
                "VALIDATION_ERROR",
                "action is required when accepting a Calling Card.",
                status_code=422,
            )

        try:
            auth = await self._authz.authorize_respond(actor=user, card=card, now=now)
        except AppError as exc:
            if exc.code == "PRESENCE_NO_LONGER_VALID" and card.status == "pending":
                self._lifecycle.transition(
                    card, "expired", now=now, cancelled_reason="presence_no_longer_valid"
                )
                self._emit(
                    event_type="calling_card.expired",
                    card=card,
                    actor_user_id=user.id,
                    recipient_user_ids=[card.sender_user_id, card.recipient_user_id],
                    occurred_at=now,
                    payload={
                        "calling_card_id": str(card.id),
                        "status": card.status,
                        "reason": "presence_no_longer_valid",
                    },
                )
                await self._session.commit()
            raise

        self._lifecycle.transition(card, "accepted", now=now, response_action=request.action)
        grant_expires = next_venue_night_end(now, auth.venue_timezone, self._settings)
        low, high = sorted((card.sender_user_id, card.recipient_user_id))
        scopes = list(request.share_scopes) if request.action == "share_info" else []
        grant = ConnectionGrant(
            calling_card_id=card.id,
            user_a_id=low,
            user_b_id=high,
            scopes=scopes,
            created_at=now,
            expires_at=grant_expires,
        )
        self._session.add(grant)
        await self._session.flush()
        self._emit(
            event_type="calling_card.accepted",
            card=card,
            actor_user_id=user.id,
            recipient_user_ids=[card.sender_user_id, card.recipient_user_id],
            occurred_at=now,
            payload={
                "calling_card_id": str(card.id),
                "status": card.status,
                "response_action": card.response_action,
                "grant_id": str(grant.id),
            },
        )
        await self._session.commit()
        return RespondCallingCardResponse(
            card=self._summary(card),
            grant=self._grant_summary(grant),
        )

    async def cancel(
        self, *, user: User, calling_card_id: UUID, now: datetime
    ) -> CallingCardSummary:
        require_calling_cards_enabled(self._settings)
        card = await self._load_card_for_update(calling_card_id)
        if card is None:
            raise AppError("CALLING_CARD_NOT_FOUND", "Calling Card not found.", status_code=404)
        if card.sender_user_id != user.id:
            raise AppError(
                "CALLING_CARD_FORBIDDEN",
                "Only the sender may cancel this Calling Card.",
                status_code=403,
            )
        if card.status != "pending":
            raise AppError(
                "CALLING_CARD_STATE_INVALID",
                "This Calling Card is no longer pending.",
                status_code=409,
                details={"status": card.status},
            )
        self._lifecycle.transition(card, "cancelled", now=now, cancelled_reason="sender_cancelled")
        self._emit(
            event_type="calling_card.cancelled",
            card=card,
            actor_user_id=user.id,
            recipient_user_ids=[card.recipient_user_id],
            occurred_at=now,
            payload={"calling_card_id": str(card.id), "status": card.status},
        )
        await self._session.commit()
        return self._summary(card)

    async def share(
        self,
        *,
        user: User,
        calling_card_id: UUID,
        request: ShareCallingCardRequest,
        now: datetime,
    ) -> CallingCardDetailResponse:
        require_calling_cards_enabled(self._settings)
        card = await self._load_visible_card(user, calling_card_id, now=now)
        if card.status != "accepted":
            raise AppError(
                "CALLING_CARD_STATE_INVALID",
                "Share scopes can only be updated on an accepted card.",
                status_code=409,
                details={"status": card.status},
            )
        grant = await self._load_grant(card.id)
        if grant is None or grant.revoked_at is not None:
            raise AppError(
                "CONNECTION_GRANT_NOT_FOUND",
                "No active connection grant for this card.",
                status_code=404,
            )
        if user.id not in {grant.user_a_id, grant.user_b_id}:
            raise AppError("CALLING_CARD_FORBIDDEN", "Not a party to this grant.", status_code=403)
        grant.scopes = list(request.share_scopes)
        self._emit(
            event_type="calling_card.share_updated",
            card=card,
            actor_user_id=user.id,
            recipient_user_ids=[
                uid for uid in (card.sender_user_id, card.recipient_user_id) if uid != user.id
            ],
            occurred_at=now,
            payload={
                "calling_card_id": str(card.id),
                "grant_id": str(grant.id),
                "scopes": list(grant.scopes),
            },
        )
        await self._session.commit()
        return CallingCardDetailResponse(card=self._summary(card), grant=self._grant_summary(grant))

    async def discoverable_users(self, *, user: User, now: datetime) -> DiscoverableUsersResponse:
        require_calling_cards_enabled(self._settings)
        self._authz._assert_active(user, role="sender")
        self._authz._assert_privacy_allows_cards(user, role="sender")

        try:
            lease = await self._leases.read(user.id)
        except RedisError as exc:
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "Presence cache is unavailable.",
                status_code=503,
                details={"reason": "presence_cache_unavailable", "retryable": True},
            ) from exc
        self._authz._assert_verified_lease(lease, role="sender", now=now, sensitive=False)
        assert lease is not None
        venue_id = lease.venue_id

        try:
            member_ids = await self._redis.zrange(
                venue_discoverable_key(venue_id),
                0,
                self._settings.discoverable_list_limit - 1,
            )
        except RedisError as exc:
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "Presence cache is unavailable.",
                status_code=503,
                details={"reason": "presence_cache_unavailable", "retryable": True},
            ) from exc

        blocked = await self._authz.blocked_user_ids(user.id)
        items: list[DiscoverableUser] = []
        for raw in member_ids:
            try:
                other_id = UUID(str(raw))
            except ValueError:
                continue
            if other_id == user.id or other_id in blocked:
                continue
            other_lease = await self._leases.read(other_id)
            if (
                other_lease is None
                or other_lease.state != "verified"
                or other_lease.venue_id != venue_id
                or now >= other_lease.verified_until
                or other_lease.ghost_mode
                or not other_lease.discoverable
            ):
                continue
            result = await self._session.execute(select(User).where(User.id == other_id))
            other = result.scalar_one_or_none()
            if other is None or other.account_status != "active" or other.deleted_at is not None:
                continue
            privacy: UserPrivacySettings | None = other.privacy
            if (
                privacy is None
                or privacy.ghost_mode
                or not privacy.discoverable_in_venue
                or not privacy.allow_calling_cards
            ):
                continue
            items.append(
                DiscoverableUser(
                    user_id=other.id,
                    handle=other.handle,
                    display_name=other.display_name,
                )
            )
            if len(items) >= self._settings.discoverable_list_limit:
                break

        return DiscoverableUsersResponse(venue_id=venue_id, items=items)

    async def block_user(
        self,
        *,
        user: User,
        blocked_user_id: UUID,
        request: BlockUserRequest,
        now: datetime,
    ) -> BlockResponse:
        if user.id == blocked_user_id:
            raise AppError("BLOCK_SELF", "You cannot block yourself.", status_code=400)
        target = await self._session.get(User, blocked_user_id)
        if target is None:
            raise AppError("USER_NOT_FOUND", "User not found.", status_code=404)

        existing = await self._session.get(UserBlock, (user.id, blocked_user_id))
        if existing is None:
            block = UserBlock(
                blocker_user_id=user.id,
                blocked_user_id=blocked_user_id,
                reason_code=request.reason_code,
                created_at=now,
            )
            self._session.add(block)
            created_at = now
        else:
            created_at = existing.created_at

        await self._cancel_pending_between(user.id, blocked_user_id, now=now)
        await self._revoke_grants_between(user.id, blocked_user_id, now=now)

        # Drop mutual discoverability memberships if either is listed.
        await self._drop_discoverability(user.id)
        await self._drop_discoverability(blocked_user_id)

        self._session.add(
            OutboxEvent(
                aggregate_type="user_block",
                aggregate_id=user.id,
                event_type="user.blocked",
                payload={
                    "blocker_user_id": str(user.id),
                    "blocked_user_id": str(blocked_user_id),
                    "reason_code": request.reason_code,
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()
        return BlockResponse(
            blocker_user_id=user.id,
            blocked_user_id=blocked_user_id,
            created_at=created_at,
        )

    async def unblock_user(
        self, *, user: User, blocked_user_id: UUID, now: datetime
    ) -> UnblockResponse:
        block = await self._session.get(UserBlock, (user.id, blocked_user_id))
        removed = False
        if block is not None:
            await self._session.delete(block)
            removed = True
            self._session.add(
                OutboxEvent(
                    aggregate_type="user_block",
                    aggregate_id=user.id,
                    event_type="user.unblocked",
                    payload={
                        "blocker_user_id": str(user.id),
                        "blocked_user_id": str(blocked_user_id),
                    },
                    occurred_at=now,
                    available_at=now,
                )
            )
            await self._session.commit()
        return UnblockResponse(
            blocker_user_id=user.id,
            blocked_user_id=blocked_user_id,
            removed=removed,
        )

    async def _cancel_pending_between(self, a: UUID, b: UUID, *, now: datetime) -> None:
        low, high = sorted((a, b))
        result = await self._session.execute(
            select(CallingCard)
            .where(
                CallingCard.pair_low == low,
                CallingCard.pair_high == high,
                CallingCard.status == "pending",
            )
            .with_for_update()
        )
        for card in result.scalars().all():
            self._lifecycle.transition(card, "blocked", now=now, cancelled_reason="user_blocked")
            self._emit(
                event_type="calling_card.blocked",
                card=card,
                actor_user_id=a,
                recipient_user_ids=[card.sender_user_id, card.recipient_user_id],
                occurred_at=now,
                payload={
                    "calling_card_id": str(card.id),
                    "status": card.status,
                    "reason": "user_blocked",
                },
            )

    async def _revoke_grants_between(self, a: UUID, b: UUID, *, now: datetime) -> None:
        low, high = sorted((a, b))
        result = await self._session.execute(
            select(ConnectionGrant).where(
                ConnectionGrant.user_a_id == low,
                ConnectionGrant.user_b_id == high,
                ConnectionGrant.revoked_at.is_(None),
            )
        )
        for grant in result.scalars().all():
            grant.revoked_at = now
            grant.revoked_reason = "user_blocked"

    async def _drop_discoverability(self, user_id: UUID) -> None:
        try:
            lease = await self._leases.read(user_id)
        except RedisError:
            return
        if lease is None:
            return
        try:
            await self._redis.zrem(venue_discoverable_key(lease.venue_id), str(user_id))
        except RedisError:
            logger.warning("discoverability_drop_failed", user_id=str(user_id))

    async def _load_by_idempotency(self, sender_id: UUID, key: str) -> CallingCard | None:
        result = await self._session.execute(
            select(CallingCard).where(
                CallingCard.sender_user_id == sender_id,
                CallingCard.idempotency_key == key,
            )
        )
        return result.scalar_one_or_none()

    async def _load_card_for_update(self, calling_card_id: UUID) -> CallingCard | None:
        result = await self._session.execute(
            select(CallingCard).where(CallingCard.id == calling_card_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def _load_visible_card(
        self, user: User, calling_card_id: UUID, *, now: datetime
    ) -> CallingCard:
        result = await self._session.execute(
            select(CallingCard).where(CallingCard.id == calling_card_id)
        )
        card = result.scalar_one_or_none()
        if card is None:
            raise AppError("CALLING_CARD_NOT_FOUND", "Calling Card not found.", status_code=404)
        if user.id not in {card.sender_user_id, card.recipient_user_id}:
            raise AppError("CALLING_CARD_NOT_FOUND", "Calling Card not found.", status_code=404)
        if card.status == "pending" and now >= card.expires_at:
            locked = await self._load_card_for_update(card.id)
            if locked is not None and locked.status == "pending" and now >= locked.expires_at:
                self._lifecycle.transition(
                    locked, "expired", now=now, cancelled_reason="ttl_elapsed"
                )
                await self._session.commit()
                return locked
        return card

    async def _load_grant(self, calling_card_id: UUID) -> ConnectionGrant | None:
        result = await self._session.execute(
            select(ConnectionGrant).where(ConnectionGrant.calling_card_id == calling_card_id)
        )
        return result.scalar_one_or_none()

    async def _expire_due_for_user(self, user_id: UUID, *, now: datetime) -> None:
        result = await self._session.execute(
            select(CallingCard)
            .where(
                CallingCard.status == "pending",
                CallingCard.expires_at <= now,
                or_(
                    CallingCard.sender_user_id == user_id,
                    CallingCard.recipient_user_id == user_id,
                ),
            )
            .with_for_update()
        )
        changed = False
        for card in result.scalars().all():
            self._lifecycle.transition(card, "expired", now=now, cancelled_reason="ttl_elapsed")
            changed = True
        if changed:
            await self._session.commit()

    def _emit(
        self,
        *,
        event_type: str,
        card: CallingCard,
        actor_user_id: UUID,
        recipient_user_ids: list[UUID],
        occurred_at: datetime,
        payload: dict[str, object],
    ) -> None:
        envelope = {
            **payload,
            "actor_user_id": str(actor_user_id),
            "recipient_user_ids": [str(uid) for uid in recipient_user_ids],
        }
        self._session.add(
            OutboxEvent(
                aggregate_type="calling_card",
                aggregate_id=card.id,
                event_type=event_type,
                payload=envelope,
                occurred_at=occurred_at,
                available_at=occurred_at,
            )
        )

    @staticmethod
    def _summary(card: CallingCard) -> CallingCardSummary:
        return CallingCardSummary(
            id=card.id,
            status=card.status,  # type: ignore[arg-type]
            venue_id=card.venue_id,
            sender_user_id=card.sender_user_id,
            recipient_user_id=card.recipient_user_id,
            reason_code=card.reason_code,
            reason_text=card.reason_text,
            created_at=card.created_at,
            expires_at=card.expires_at,
            responded_at=card.responded_at,
            response_action=card.response_action,  # type: ignore[arg-type]
        )

    @staticmethod
    def _grant_summary(grant: ConnectionGrant | None) -> ConnectionGrantSummary | None:
        if grant is None:
            return None
        return ConnectionGrantSummary(
            id=grant.id,
            calling_card_id=grant.calling_card_id,
            scopes=[str(s) for s in grant.scopes],
            expires_at=grant.expires_at,
            revoked_at=grant.revoked_at,
        )
