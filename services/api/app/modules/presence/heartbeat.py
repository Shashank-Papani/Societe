"""Server-authoritative presence retention heartbeats.

Clients submit location evidence only. The server computes distance, renews
leases inside the retention radius, confirms exits with hysteresis, and never
logs the user out when venue presence ends.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import CheckIn, OutboxEvent, User, UserDevice, Venue
from app.modules.presence.geospatial import describe_venue_for_point
from app.modules.presence.leases import LeaseWrite, PresenceLeaseStore
from app.modules.presence.policy import (
    PresencePolicy,
    resolve_venue_policy,
    within_retention_radius,
)
from app.modules.presence.rate_limit import LocationRateLimiter
from app.modules.presence.schemas import (
    HeartbeatRequest,
    PresenceData,
    PresenceState,
    PresenceVenue,
)

logger = get_logger(__name__)

ACTIVE_RETENTION_STATES = ("provisional", "verified", "rechecking", "degraded")


@dataclass(frozen=True)
class HeartbeatResult:
    data: PresenceData


class PresenceHeartbeatService:
    def __init__(self, session: AsyncSession, redis: Redis[str], settings: Settings) -> None:
        self._session = session
        self._redis = redis
        self._settings = settings
        self._leases = PresenceLeaseStore(redis)
        self._rate_limiter = LocationRateLimiter(
            redis,
            per_user_per_minute=settings.location_rate_limit_per_user_per_minute,
            per_device_per_minute=settings.location_rate_limit_per_device_per_minute,
        )

    async def heartbeat(
        self,
        *,
        user: User,
        request: HeartbeatRequest,
        received_at: datetime,
        allow_simulated: bool = False,
    ) -> PresenceData:
        device = await self._load_device(user, request.device_id)
        await self._rate_limiter.check(user_id=user.id, device_id=device.id, now=received_at)

        signals = request.platform_signals
        if (signals.is_mock or signals.is_simulated) and not allow_simulated:
            return PresenceData(
                state="rejected",
                decision="reject",
                reasons=["mock_location"],
                social_features_enabled=False,
            )

        active = await self._load_active(user.id, for_update=True)
        if active is None:
            return PresenceData(
                state="outside",
                decision="no_active_presence",
                reasons=["no_active_presence"],
                social_features_enabled=False,
            )

        if request.check_in_id is not None and request.check_in_id != active.id:
            return PresenceData(
                state="outside",
                decision="presence_ended",
                reasons=["presence_mismatch"],
                social_features_enabled=False,
            )
        if request.venue_id is not None and request.venue_id != active.venue_id:
            return PresenceData(
                state="outside",
                decision="presence_ended",
                reasons=["venue_mismatch"],
                social_features_enabled=False,
            )

        venue_row = await self._session.execute(select(Venue).where(Venue.id == active.venue_id))
        venue = venue_row.scalar_one_or_none()
        if venue is None or venue.status != "active":
            return await self._end_presence(
                user=user,
                active=active,
                received_at=received_at,
                reason="venue_inactive",
                decision="exit",
            )

        policy = resolve_venue_policy(self._settings, venue)
        age_seconds = (received_at - request.observed_at).total_seconds()
        accuracy = request.location.horizontal_accuracy_m
        evidence_accepted = (
            age_seconds <= policy.max_evidence_age_seconds
            and age_seconds >= -self._settings.max_observed_future_skew_seconds
            and accuracy <= policy.maximum_location_accuracy_meters
        )

        candidate = await describe_venue_for_point(
            self._session,
            active.venue_id,
            request.location.latitude,
            request.location.longitude,
        )
        distance = (
            0.0
            if candidate is not None and candidate.inside
            else (candidate.centroid_distance_m if candidate is not None else None)
        )

        # Stale / poor evidence never counts as outside confirmation.
        if not evidence_accepted or distance is None:
            return await self._handle_unreliable_evidence(
                user=user,
                active=active,
                venue=venue,
                policy=policy,
                received_at=received_at,
                distance=distance,
                accuracy=accuracy,
                reasons=(
                    ["stale_evidence"]
                    if age_seconds > policy.max_evidence_age_seconds
                    else (
                        ["observed_at_in_future"]
                        if age_seconds < -self._settings.max_observed_future_skew_seconds
                        else (
                            ["accuracy_exceeds_venue_maximum"]
                            if accuracy > policy.maximum_location_accuracy_meters
                            else ["location_unavailable"]
                        )
                    )
                ),
            )

        active.last_evidence_observed_at = request.observed_at.astimezone(UTC)
        active.last_location_accuracy_meters = accuracy
        active.last_distance_meters = distance
        active.updated_at = received_at

        if within_retention_radius(distance_meters=distance, policy=policy):
            return await self._renew_inside(
                user=user,
                active=active,
                venue=venue,
                policy=policy,
                received_at=received_at,
                distance=distance,
            )

        return await self._handle_outside(
            user=user,
            active=active,
            venue=venue,
            policy=policy,
            received_at=received_at,
            distance=distance,
        )

    async def _handle_unreliable_evidence(
        self,
        *,
        user: User,
        active: CheckIn,
        venue: Venue,
        policy: PresencePolicy,
        received_at: datetime,
        distance: float | None,
        accuracy: float,
        reasons: list[str],
    ) -> PresenceData:
        verified_until = active.verified_until
        grace_until = active.grace_until
        if verified_until is not None and received_at < verified_until:
            # Lease still valid — keep ACTIVE / RECHECKING without renewing.
            state: PresenceState = "rechecking" if active.state == "rechecking" else "verified"
            return await self._project(
                user=user,
                active=active,
                venue=venue,
                policy=policy,
                state=state,
                decision="hold",
                reasons=reasons,
                distance=distance,
                lease_expires_at=verified_until,
                grace_expires_at=grace_until,
                next_check=received_at + timedelta(seconds=60),
                outside_pending=active.outside_confirmation_count > 0,
                renew_valkey=False,
            )

        if grace_until is not None and received_at < grace_until:
            if active.state != "degraded":
                active.state = "degraded"
                active.updated_at = received_at
                self._emit(active, "presence.grace", received_at)
                await self._session.commit()
            return await self._project(
                user=user,
                active=active,
                venue=venue,
                policy=policy,
                state="degraded",
                decision="grace",
                reasons=[*reasons, "lease_expired_in_grace"],
                distance=distance,
                lease_expires_at=verified_until,
                grace_expires_at=grace_until,
                next_check=received_at + timedelta(seconds=60),
                outside_pending=False,
                renew_valkey=True,
            )

        return await self._end_presence(
            user=user,
            active=active,
            received_at=received_at,
            reason="lease_expired",
            decision="expired",
        )

    async def _renew_inside(
        self,
        *,
        user: User,
        active: CheckIn,
        venue: Venue,
        policy: PresencePolicy,
        received_at: datetime,
        distance: float,
    ) -> PresenceData:
        proposed_until = received_at + timedelta(seconds=policy.lease_seconds)
        # Never shorten a newer lease with a stale/concurrent heartbeat.
        if active.verified_until is not None and active.verified_until > proposed_until:
            verified_until = active.verified_until
        else:
            verified_until = proposed_until
        grace_until = verified_until + timedelta(seconds=policy.grace_seconds)

        prior_state = active.state
        active.state = "verified"
        active.verified_until = verified_until
        active.grace_until = grace_until
        active.lease_expires_at = grace_until
        active.last_valid_evidence_at = received_at
        active.last_verified_at = received_at
        if active.verified_at is None:
            active.verified_at = received_at
        active.outside_confirmation_count = 0
        active.first_outside_observed_at = None
        active.last_outside_observed_at = None
        active.updated_at = received_at

        if prior_state != "verified":
            self._emit(active, "presence.renewed", received_at)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise AppError(
                "PRESENCE_CONFLICT",
                "Concurrent presence update; retry with fresh evidence.",
                status_code=409,
            ) from exc

        return await self._project(
            user=user,
            active=active,
            venue=venue,
            policy=policy,
            state="verified",
            decision="renewed",
            reasons=["inside_retention_radius"],
            distance=distance,
            lease_expires_at=verified_until,
            grace_expires_at=grace_until,
            next_check=received_at + timedelta(seconds=180),
            outside_pending=False,
            renew_valkey=True,
        )

    async def _handle_outside(
        self,
        *,
        user: User,
        active: CheckIn,
        venue: Venue,
        policy: PresencePolicy,
        received_at: datetime,
        distance: float,
    ) -> PresenceData:
        count = int(active.outside_confirmation_count or 0)
        first_outside = active.first_outside_observed_at

        if count <= 0 or first_outside is None:
            active.state = "rechecking"
            active.outside_confirmation_count = 1
            active.first_outside_observed_at = received_at
            active.last_outside_observed_at = received_at
            active.updated_at = received_at
            self._emit(active, "presence.rechecking", received_at)
            await self._session.commit()
            next_check = received_at + timedelta(seconds=policy.outside_confirmation_delay_seconds)
            return await self._project(
                user=user,
                active=active,
                venue=venue,
                policy=policy,
                state="rechecking",
                decision="rechecking_outside",
                reasons=["outside_retention_pending_confirmation"],
                distance=distance,
                lease_expires_at=active.verified_until,
                grace_expires_at=active.grace_until,
                next_check=next_check,
                outside_pending=True,
                renew_valkey=True,
            )

        elapsed = (received_at - first_outside.astimezone(UTC)).total_seconds()
        if elapsed < policy.outside_confirmation_delay_seconds:
            active.last_outside_observed_at = received_at
            active.updated_at = received_at
            await self._session.commit()
            next_check = first_outside.astimezone(UTC) + timedelta(
                seconds=policy.outside_confirmation_delay_seconds
            )
            return await self._project(
                user=user,
                active=active,
                venue=venue,
                policy=policy,
                state="rechecking",
                decision="rechecking_outside",
                reasons=["outside_confirmation_too_early"],
                distance=distance,
                lease_expires_at=active.verified_until,
                grace_expires_at=active.grace_until,
                next_check=next_check,
                outside_pending=True,
                renew_valkey=False,
            )

        # Second confirmed outside sample — revoke venue presence only.
        return await self._end_presence(
            user=user,
            active=active,
            received_at=received_at,
            reason="left_retention_radius",
            decision="revoked",
            distance=distance,
            venue=venue,
            policy=policy,
        )

    async def _end_presence(
        self,
        *,
        user: User,
        active: CheckIn,
        received_at: datetime,
        reason: str,
        decision: str,
        distance: float | None = None,
        venue: Venue | None = None,
        policy: PresencePolicy | None = None,
    ) -> PresenceData:
        venue_id = active.venue_id
        active.state = "exited" if reason == "lease_expired" else "revoked"
        if reason == "lease_expired":
            active.state = "exited"
        elif reason == "left_retention_radius":
            active.state = "revoked"
        else:
            active.state = "exited"
        active.exited_at = received_at
        active.exit_reason = reason
        active.updated_at = received_at
        self._emit(active, "presence.ended", received_at)
        await self._session.commit()
        try:
            await self._leases.clear(user.id, venue_id=venue_id)
        except RedisError:
            logger.error("presence_heartbeat_lease_clear_failed", user_id=str(user.id))

        return PresenceData(
            state="exited",
            venue=PresenceVenue(id=venue.id, name=venue.name) if venue is not None else None,
            verification_level=None,
            lease_expires_at=None,
            grace_expires_at=None,
            entry_radius_meters=policy.entry_radius_meters if policy else None,
            retention_radius_meters=policy.retention_radius_meters if policy else None,
            distance_meters=distance,
            next_recommended_check_at=None,
            outside_confirmation_pending=False,
            social_features_enabled=False,
            decision=decision,
            reasons=[reason],
        )

    async def _project(
        self,
        *,
        user: User,
        active: CheckIn,
        venue: Venue,
        policy: PresencePolicy,
        state: PresenceState,
        decision: str,
        reasons: list[str],
        distance: float | None,
        lease_expires_at: datetime | None,
        grace_expires_at: datetime | None,
        next_check: datetime | None,
        outside_pending: bool,
        renew_valkey: bool,
    ) -> PresenceData:
        ghost, discoverable, allow_cards = self._privacy_flags(user)
        valkey_ok = True
        if renew_valkey:
            try:
                effective_grace = grace_expires_at or lease_expires_at or datetime.now(UTC)
                await self._leases.update(
                    LeaseWrite(
                        user_id=user.id,
                        venue_id=venue.id,
                        check_in_id=active.id,
                        # Social membership stays verified during rechecking.
                        state="verified" if state in {"verified", "rechecking"} else state,
                        confidence=active.confidence_score,
                        verification_level=active.verification_level,
                        ghost_mode=ghost,
                        discoverable=discoverable,
                        verified_until=lease_expires_at or effective_grace,
                        grace_until=effective_grace,
                        lease_version=active.geofence_version,
                        previous_venue_id=venue.id,
                    )
                )
            except RedisError:
                logger.error("presence_heartbeat_lease_write_failed", user_id=str(user.id))
                valkey_ok = False

        social = (
            state in {"verified", "rechecking"}
            and valkey_ok
            and not ghost
            and discoverable
            and allow_cards
            and user.account_status == "active"
            and user.deleted_at is None
        )
        # Grace: keep existing connections discoverable briefly; block new sensitive actions
        # via verified_until checks elsewhere. Presence UI remains temporarily active.
        if state == "degraded":
            social = False

        level = (
            active.verification_level if active.verification_level in {"weak", "standard"} else None
        )
        return PresenceData(
            state=state,
            venue=PresenceVenue(id=venue.id, name=venue.name),
            verification_level=level  # type: ignore[arg-type]
            if state in {"verified", "rechecking", "provisional"}
            else None,
            lease_expires_at=lease_expires_at if valkey_ok else None,
            grace_expires_at=grace_expires_at,
            entry_radius_meters=policy.entry_radius_meters,
            retention_radius_meters=policy.retention_radius_meters,
            distance_meters=distance,
            next_recommended_check_at=next_check,
            outside_confirmation_pending=outside_pending,
            social_features_enabled=social,
            decision=decision,
            reasons=reasons,
        )

    def _privacy_flags(self, user: User) -> tuple[bool, bool, bool]:
        privacy = user.privacy
        if privacy is None:
            return True, False, False
        ghost = privacy.ghost_mode
        discoverable = False if ghost else privacy.discoverable_in_venue
        allow_cards = False if ghost else privacy.allow_calling_cards
        return ghost, discoverable, allow_cards

    def _emit(self, check_in: CheckIn, event_type: str, occurred_at: datetime) -> None:
        self._session.add(
            OutboxEvent(
                aggregate_type="check_in",
                aggregate_id=check_in.id,
                event_type=event_type,
                payload={
                    "user_id": str(check_in.user_id),
                    "venue_id": str(check_in.venue_id),
                    "check_in_id": str(check_in.id),
                    "state": check_in.state,
                    "verification_level": check_in.verification_level,
                    "occurred_at": occurred_at.isoformat(),
                },
                occurred_at=occurred_at,
                available_at=occurred_at,
            )
        )

    async def _load_device(self, user: User, device_id: UUID) -> UserDevice:
        result = await self._session.execute(select(UserDevice).where(UserDevice.id == device_id))
        device = result.scalar_one_or_none()
        if device is None:
            raise AppError("DEVICE_NOT_FOUND", "Device not registered.", status_code=404)
        if device.user_id != user.id:
            raise AppError(
                "DEVICE_NOT_OWNED",
                "This device is not registered to the authenticated account.",
                status_code=403,
            )
        if device.revoked_at is not None:
            raise AppError("DEVICE_REVOKED", "This device has been revoked.", status_code=403)
        return device

    async def _load_active(self, user_id: UUID, *, for_update: bool = False) -> CheckIn | None:
        stmt = (
            select(CheckIn)
            .where(CheckIn.user_id == user_id, CheckIn.state.in_(ACTIVE_RETENTION_STATES))
            .order_by(CheckIn.entered_at.desc())
            .limit(1)
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
