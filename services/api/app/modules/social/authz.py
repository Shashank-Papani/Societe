"""Calling Card authorization (architecture §14).

Venue identity always comes from fresh Valkey leases — never from a
client-supplied venue id on create or discover. Ghost Mode,
``discoverable_in_venue=false``, and ``allow_calling_cards=false`` block send
**and** receive.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import CallingCard, CheckIn, User, UserBlock, UserPrivacySettings, Venue
from app.modules.presence.geospatial import get_venue_timezone
from app.modules.presence.leases import LeaseSnapshot, PresenceLeaseStore
from app.modules.social.lifecycle import venue_night_id
from app.modules.social.rates import CallingCardRateLimiter

logger = get_logger(__name__)

RETRYABLE_PRESENCE_REASONS = frozenset(
    {
        "presence_refresh_required",
        "presence_provisional",
        "presence_degraded",
        "presence_cache_unavailable",
        "presence_lease_stale",
        "presence_lease_insufficient",
    }
)


@dataclass(frozen=True)
class CallingCardSendAuthorization:
    venue_id: UUID
    sender_check_in_id: UUID
    recipient_check_in_id: UUID
    venue_timezone: str
    venue_night: str


def require_calling_cards_enabled(settings: Settings) -> None:
    if not settings.ff_calling_cards:
        raise AppError(
            "CALLING_CARDS_DISABLED",
            "Calling Cards are not enabled.",
            status_code=404,
        )


class CallingCardAuthorizer:
    def __init__(self, session: AsyncSession, redis: Redis[str], settings: Settings) -> None:
        self._session = session
        self._redis = redis
        self._settings = settings
        self._leases = PresenceLeaseStore(redis)
        self._limits = CallingCardRateLimiter(redis, settings)

    async def authorize_send(
        self,
        *,
        sender: User,
        recipient_user_id: UUID,
        now: datetime,
        consume_rate_limit: bool = True,
    ) -> CallingCardSendAuthorization:
        # 1. authenticated sender exists and is active
        self._assert_active(sender, role="sender")

        # 2. recipient exists and is active
        recipient = await self._load_user(recipient_user_id)
        if recipient is None:
            raise AppError(
                "RECIPIENT_NOT_FOUND",
                "Recipient was not found.",
                status_code=404,
            )
        self._assert_active(recipient, role="recipient")

        # 3. sender is not recipient
        if sender.id == recipient.id:
            raise AppError(
                "CALLING_CARD_SELF",
                "You cannot send a Calling Card to yourself.",
                status_code=400,
            )

        # 4. neither user has blocked the other
        if await self.is_blocked(sender.id, recipient.id):
            raise AppError(
                "CALLING_CARD_BLOCKED",
                "Calling Cards are not available with this user.",
                status_code=403,
            )

        # 5-6. privacy for both
        self._assert_privacy_allows_cards(sender, role="sender")
        self._assert_privacy_allows_cards(recipient, role="recipient")

        # 7-13. leases + freshness
        sender_lease = await self._read_lease(sender.id)
        recipient_lease = await self._read_lease(recipient.id)
        self._assert_verified_lease(sender_lease, role="sender", now=now, sensitive=True)
        self._assert_verified_lease(recipient_lease, role="recipient", now=now, sensitive=False)
        assert sender_lease is not None and recipient_lease is not None

        if sender_lease.venue_id != recipient_lease.venue_id:
            raise AppError(
                "CALLING_CARD_VENUE_MISMATCH",
                "Both users must be verified at the same venue.",
                status_code=403,
                details={"reason": "presence_venue_mismatch"},
            )

        venue_id = sender_lease.venue_id
        if sender_lease.check_in_id is None or recipient_lease.check_in_id is None:
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "A verified check-in is required.",
                status_code=403,
                details={"reason": "presence_refresh_required", "retryable": True},
            )

        await self._assert_active_check_in(
            check_in_id=sender_lease.check_in_id,
            user_id=sender.id,
            venue_id=venue_id,
            now=now,
        )
        await self._assert_active_check_in(
            check_in_id=recipient_lease.check_in_id,
            user_id=recipient.id,
            venue_id=venue_id,
            now=now,
        )

        # 14. age / venue policy
        await self._assert_venue_policy(sender, recipient, venue_id)

        venue_timezone = await get_venue_timezone(self._session, venue_id) or (
            self._settings.default_purge_timezone
        )
        night = venue_night_id(now, venue_timezone, self._settings)

        # 15. rate limits
        if consume_rate_limit:
            await self._limits.check_send(
                user_id=sender.id,
                venue_id=venue_id,
                venue_night=night,
                now=now,
            )

        # 16. no pending card for the pair
        if await self._pending_pair_exists(sender.id, recipient.id, venue_id):
            raise AppError(
                "CALLING_CARD_PENDING_EXISTS",
                "A pending Calling Card already exists for this pair.",
                status_code=409,
            )

        # 17. decline cooldown
        if await self._in_decline_cooldown(sender.id, recipient.id, venue_id, now=now):
            raise AppError(
                "CALLING_CARD_DECLINE_COOLDOWN",
                "Please wait before sending another Calling Card to this user.",
                status_code=429,
                details={"cooldown_seconds": self._settings.decline_cooldown_seconds},
            )

        # 18. device/account risk — Phase 4 accepts active accounts; attestation
        # gates land with App Attest / Play Integrity later.
        return CallingCardSendAuthorization(
            venue_id=venue_id,
            sender_check_in_id=sender_lease.check_in_id,
            recipient_check_in_id=recipient_lease.check_in_id,
            venue_timezone=venue_timezone,
            venue_night=night,
        )

    async def authorize_respond(
        self,
        *,
        actor: User,
        card: CallingCard,
        now: datetime,
    ) -> CallingCardSendAuthorization:
        """Re-run checks 1-13 for acceptance. Decline uses a lighter path."""
        self._assert_active(actor, role="recipient")
        if actor.id != card.recipient_user_id:
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
        if now >= card.expires_at:
            raise AppError(
                "CALLING_CARD_EXPIRED",
                "This Calling Card has expired.",
                status_code=409,
            )

        sender = await self._load_user(card.sender_user_id)
        if sender is None:
            raise AppError(
                "PRESENCE_NO_LONGER_VALID",
                "Presence is no longer valid for this Calling Card.",
                status_code=409,
                details={"reason": "sender_missing"},
            )
        self._assert_active(sender, role="sender")
        self._assert_active(actor, role="recipient")

        if await self.is_blocked(sender.id, actor.id):
            raise AppError(
                "CALLING_CARD_BLOCKED",
                "Calling Cards are not available with this user.",
                status_code=403,
            )

        self._assert_privacy_allows_cards(sender, role="sender")
        self._assert_privacy_allows_cards(actor, role="recipient")

        sender_lease = await self._read_lease(sender.id)
        recipient_lease = await self._read_lease(actor.id)
        try:
            self._assert_verified_lease(sender_lease, role="sender", now=now, sensitive=True)
            self._assert_verified_lease(recipient_lease, role="recipient", now=now, sensitive=False)
        except AppError as exc:
            if exc.code == "CALLING_CARD_NOT_AUTHORIZED":
                raise AppError(
                    "PRESENCE_NO_LONGER_VALID",
                    "Presence is no longer valid for this Calling Card.",
                    status_code=409,
                    details=exc.details,
                ) from exc
            raise

        assert sender_lease is not None and recipient_lease is not None
        if (
            sender_lease.venue_id != card.venue_id
            or recipient_lease.venue_id != card.venue_id
            or sender_lease.venue_id != recipient_lease.venue_id
        ):
            raise AppError(
                "PRESENCE_NO_LONGER_VALID",
                "Presence is no longer valid for this Calling Card.",
                status_code=409,
                details={"reason": "presence_venue_mismatch"},
            )
        if sender_lease.check_in_id is None or recipient_lease.check_in_id is None:
            raise AppError(
                "PRESENCE_NO_LONGER_VALID",
                "Presence is no longer valid for this Calling Card.",
                status_code=409,
                details={"reason": "presence_refresh_required"},
            )

        try:
            await self._assert_active_check_in(
                check_in_id=sender_lease.check_in_id,
                user_id=sender.id,
                venue_id=card.venue_id,
                now=now,
            )
            await self._assert_active_check_in(
                check_in_id=recipient_lease.check_in_id,
                user_id=actor.id,
                venue_id=card.venue_id,
                now=now,
            )
        except AppError as exc:
            raise AppError(
                "PRESENCE_NO_LONGER_VALID",
                "Presence is no longer valid for this Calling Card.",
                status_code=409,
                details=exc.details,
            ) from exc

        venue_timezone = await get_venue_timezone(self._session, card.venue_id) or (
            self._settings.default_purge_timezone
        )
        return CallingCardSendAuthorization(
            venue_id=card.venue_id,
            sender_check_in_id=sender_lease.check_in_id,
            recipient_check_in_id=recipient_lease.check_in_id,
            venue_timezone=venue_timezone,
            venue_night=venue_night_id(now, venue_timezone, self._settings),
        )

    async def is_blocked(self, a: UUID, b: UUID) -> bool:
        result = await self._session.execute(
            select(func.count())
            .select_from(UserBlock)
            .where(
                or_(
                    and_(UserBlock.blocker_user_id == a, UserBlock.blocked_user_id == b),
                    and_(UserBlock.blocker_user_id == b, UserBlock.blocked_user_id == a),
                )
            )
        )
        return int(result.scalar_one()) > 0

    async def blocked_user_ids(self, user_id: UUID) -> set[UUID]:
        result = await self._session.execute(
            select(UserBlock.blocker_user_id, UserBlock.blocked_user_id).where(
                or_(
                    UserBlock.blocker_user_id == user_id,
                    UserBlock.blocked_user_id == user_id,
                )
            )
        )
        blocked: set[UUID] = set()
        for blocker, blocked_id in result.all():
            other = blocked_id if blocker == user_id else blocker
            blocked.add(other)
        return blocked

    async def _load_user(self, user_id: UUID) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    def _assert_active(user: User, *, role: str) -> None:
        if user.account_status != "active" or user.deleted_at is not None:
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                f"The {role} account is not available.",
                status_code=403,
                details={"reason": "account_not_active", "role": role},
            )
        if user.onboarding_state == "age_ineligible":
            raise AppError(
                "AGE_INELIGIBLE",
                f"The {role} account does not meet the minimum age requirement.",
                status_code=403,
                details={"reason": "age_ineligible", "role": role},
            )
        if user.onboarding_state != "completed":
            raise AppError(
                "ONBOARDING_INCOMPLETE",
                f"The {role} must finish onboarding before using Calling Cards.",
                status_code=403,
                details={"reason": "onboarding_incomplete", "role": role},
            )

    @staticmethod
    def _assert_privacy_allows_cards(user: User, *, role: str) -> None:
        privacy: UserPrivacySettings | None = user.privacy
        if privacy is None:
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                f"Privacy settings missing for {role}.",
                status_code=403,
                details={"reason": "privacy_missing", "role": role},
            )
        if privacy.ghost_mode:
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "Ghost Mode blocks Calling Cards.",
                status_code=403,
                details={"reason": "ghost_mode", "role": role},
            )
        if not privacy.discoverable_in_venue:
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "Discoverability is required for Calling Cards.",
                status_code=403,
                details={"reason": "not_discoverable", "role": role},
            )
        if not privacy.allow_calling_cards:
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "Calling Cards are disabled in privacy settings.",
                status_code=403,
                details={"reason": "calling_cards_disabled", "role": role},
            )

    async def _read_lease(self, user_id: UUID) -> LeaseSnapshot | None:
        try:
            return await self._leases.read(user_id)
        except RedisError:
            logger.error("calling_card_lease_read_failed", user_id=str(user_id))
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "Presence cache is unavailable.",
                status_code=503,
                details={"reason": "presence_cache_unavailable", "retryable": True},
            ) from None

    def _assert_verified_lease(
        self,
        lease: LeaseSnapshot | None,
        *,
        role: str,
        now: datetime,
        sensitive: bool,
    ) -> None:
        if lease is None:
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "A verified presence lease is required.",
                status_code=403,
                details={"reason": "presence_refresh_required", "role": role, "retryable": True},
            )
        if lease.state != "verified":
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "A verified presence lease is required.",
                status_code=403,
                details={
                    "reason": f"presence_{lease.state}",
                    "role": role,
                    "retryable": f"presence_{lease.state}" in RETRYABLE_PRESENCE_REASONS,
                },
            )
        if now >= lease.verified_until:
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "Presence lease is stale.",
                status_code=403,
                details={"reason": "presence_lease_stale", "role": role, "retryable": True},
            )
        if lease.ghost_mode or not lease.discoverable:
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "Discoverable verified presence is required.",
                status_code=403,
                details={"reason": "lease_not_discoverable", "role": role},
            )
        if sensitive:
            remaining = (lease.verified_until - now).total_seconds()
            if remaining < self._settings.sensitive_action_lease_min_remaining_seconds:
                raise AppError(
                    "CALLING_CARD_NOT_AUTHORIZED",
                    "Presence lease is too close to expiry for this action.",
                    status_code=403,
                    details={
                        "reason": "presence_lease_insufficient",
                        "role": role,
                        "retryable": True,
                    },
                )

    async def _assert_active_check_in(
        self,
        *,
        check_in_id: UUID,
        user_id: UUID,
        venue_id: UUID,
        now: datetime,
    ) -> None:
        result = await self._session.execute(select(CheckIn).where(CheckIn.id == check_in_id))
        check_in = result.scalar_one_or_none()
        if (
            check_in is None
            or check_in.user_id != user_id
            or check_in.venue_id != venue_id
            or check_in.state != "verified"
            or check_in.exited_at is not None
            or check_in.verified_until is None
            or now >= check_in.verified_until
        ):
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "Durable check-in is not active.",
                status_code=403,
                details={"reason": "check_in_inactive", "retryable": True},
            )

    async def _assert_venue_policy(self, sender: User, recipient: User, venue_id: UUID) -> None:
        result = await self._session.execute(select(Venue).where(Venue.id == venue_id))
        venue = result.scalar_one_or_none()
        if venue is None or venue.status != "active":
            raise AppError(
                "CALLING_CARD_NOT_AUTHORIZED",
                "Venue is not available for Calling Cards.",
                status_code=403,
                details={"reason": "venue_unavailable"},
            )
        if venue.minimum_age is not None:
            for user, role in ((sender, "sender"), (recipient, "recipient")):
                if not user.age_verified:
                    raise AppError(
                        "CALLING_CARD_NOT_AUTHORIZED",
                        "Age verification is required at this venue.",
                        status_code=403,
                        details={"reason": "age_policy", "role": role},
                    )

    async def _pending_pair_exists(
        self, sender_id: UUID, recipient_id: UUID, venue_id: UUID
    ) -> bool:
        low, high = sorted((sender_id, recipient_id))
        result = await self._session.execute(
            select(func.count())
            .select_from(CallingCard)
            .where(
                CallingCard.pair_low == low,
                CallingCard.pair_high == high,
                CallingCard.venue_id == venue_id,
                CallingCard.status == "pending",
            )
        )
        return int(result.scalar_one()) > 0

    async def _in_decline_cooldown(
        self,
        sender_id: UUID,
        recipient_id: UUID,
        venue_id: UUID,
        *,
        now: datetime,
    ) -> bool:
        since = now - timedelta(seconds=self._settings.decline_cooldown_seconds)
        # Cooldown applies when the prospective recipient previously declined
        # a card from this sender at this venue.
        result = await self._session.execute(
            select(func.count())
            .select_from(CallingCard)
            .where(
                CallingCard.sender_user_id == sender_id,
                CallingCard.recipient_user_id == recipient_id,
                CallingCard.venue_id == venue_id,
                CallingCard.status == "declined",
                CallingCard.responded_at.is_not(None),
                CallingCard.responded_at >= since,
            )
        )
        return int(result.scalar_one()) > 0
