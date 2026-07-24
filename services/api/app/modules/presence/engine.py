"""Server-authoritative presence decision engine.

Design rules that are easy to get wrong and are therefore enforced here:

* ``observed_at`` is client-controlled. It gates freshness and clock skew only.
  Every dwell, lease, and purge deadline is computed from the server's
  ``received_at``.
* Ambiguity fails closed. When two venues can explain the same point we refuse
  to guess, because a wrong guess authorizes a stranger into the wrong room.
* PostgreSQL commits before Valkey is touched. A Valkey failure costs social
  features, never the durable record.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import CheckIn, OutboxEvent, User, UserDevice
from app.modules.presence.geospatial import (
    VenueCandidate,
    describe_venue_for_point,
    find_candidates,
)
from app.modules.presence.leases import LeaseWrite, PresenceLeaseStore
from app.modules.presence.rate_limit import LocationRateLimiter
from app.modules.presence.samples import PresenceSample, SampleBuffer
from app.modules.presence.schemas import (
    EvidenceRequest,
    PresenceData,
    PresenceState,
    PresenceVenue,
    SampleVerdict,
)

logger = get_logger(__name__)

ACTIVE_CHECK_IN_STATES = ("provisional", "verified", "degraded")
DURABLE_STATES = frozenset({"provisional", "verified", "degraded"})

# A neighbour polygon this close is treated as sharing our boundary regardless of
# reported accuracy.
SHARED_BOUNDARY_EPSILON_M = 0.5

_EVIDENCE_INSERT_SQL = """
INSERT INTO ephemeral.location_evidence (
    user_id, check_in_id, observed_at, received_at, point, horizontal_accuracy_m,
    speed_mps, altitude_m, source, is_mock, is_simulated, device_attestation_status,
    risk_score, risk_reasons, purge_at
) VALUES (
    CAST(:user_id AS uuid),
    CAST(:check_in_id AS uuid),
    :observed_at,
    :received_at,
    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
    :horizontal_accuracy_m,
    :speed_mps,
    :altitude_m,
    :source,
    :is_mock,
    :is_simulated,
    :attestation_status,
    :risk_score,
    CAST(:risk_reasons AS jsonb),
    :purge_at
)
"""


@dataclass
class Decision:
    state: PresenceState
    decision: str
    reasons: list[str] = field(default_factory=list)
    venue: VenueCandidate | None = None
    durable_state: str | None = None
    exit_active: bool = False
    exit_reason: str | None = None
    verification_level: str | None = None
    confidence: int = 0
    sample_verdict: SampleVerdict = "outside"
    credible_outside: bool = False
    persist_evidence: bool = False
    risk_score: int = 0


def compute_purge_at(received_at: datetime, timezone_name: str, settings: Settings) -> datetime:
    """Next 06:00 local at the venue, capped by the absolute retention bound."""
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(settings.default_purge_timezone)
    local = received_at.astimezone(zone)
    next_six = local.replace(hour=6, minute=0, second=0, microsecond=0)
    if local >= next_six:
        next_six = next_six + timedelta(days=1)
    cap = received_at + timedelta(hours=settings.evidence_absolute_max_retention_hours)
    return min(next_six.astimezone(UTC), cap)


def _confidence_score(
    *,
    inside: bool,
    accuracy_ok: bool,
    dwell_ok: bool,
    ambiguous: bool,
    in_entry_buffer: bool,
) -> int:
    score = 40
    if inside:
        score += 30
    elif in_entry_buffer:
        score += 5
    score += 10 if accuracy_ok else -25
    if dwell_ok:
        score += 15
    if ambiguous:
        score -= 40
    return max(0, min(100, score))


class PresenceEngine:
    def __init__(self, session: AsyncSession, redis: Redis[str], settings: Settings) -> None:
        self._session = session
        self._redis = redis
        self._settings = settings
        self._leases = PresenceLeaseStore(redis)
        self._samples = SampleBuffer(
            redis,
            max_samples=settings.presence_sample_buffer_max,
            ttl_seconds=settings.presence_sample_buffer_ttl_seconds,
        )
        self._rate_limiter = LocationRateLimiter(
            redis,
            per_user_per_minute=settings.location_rate_limit_per_user_per_minute,
            per_device_per_minute=settings.location_rate_limit_per_device_per_minute,
        )

    # ---------------------------------------------------------------- helpers

    async def load_active_check_in(
        self, user_id: UUID, *, for_update: bool = False
    ) -> CheckIn | None:
        stmt = (
            select(CheckIn)
            .where(CheckIn.user_id == user_id, CheckIn.state.in_(ACTIVE_CHECK_IN_STATES))
            .order_by(CheckIn.entered_at.desc())
            .limit(1)
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    def _privacy_flags(self, user: User) -> tuple[bool, bool, bool]:
        privacy = user.privacy
        if privacy is None:
            # Absent privacy row is treated as maximally private.
            return True, False, False
        ghost = privacy.ghost_mode
        discoverable = False if ghost else privacy.discoverable_in_venue
        allow_cards = False if ghost else privacy.allow_calling_cards
        return ghost, discoverable, allow_cards

    def _account_active(self, user: User) -> bool:
        return user.account_status == "active" and user.deleted_at is None

    def _emit(
        self,
        *,
        event_type: str,
        check_in: CheckIn,
        occurred_at: datetime,
    ) -> None:
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

    async def _persist_evidence(
        self,
        *,
        user: User,
        device: UserDevice,
        request: EvidenceRequest,
        received_at: datetime,
        check_in_id: UUID | None,
        venue_timezone: str | None,
        risk_score: int,
        risk_reasons: list[str],
    ) -> None:
        purge_at = compute_purge_at(
            received_at,
            venue_timezone or self._settings.default_purge_timezone,
            self._settings,
        )
        await self._session.execute(
            text(_EVIDENCE_INSERT_SQL),
            {
                "user_id": str(user.id),
                "check_in_id": str(check_in_id) if check_in_id else None,
                "observed_at": request.observed_at,
                "received_at": received_at,
                "longitude": request.location.longitude,
                "latitude": request.location.latitude,
                "horizontal_accuracy_m": request.location.horizontal_accuracy_m,
                "speed_mps": request.location.speed_mps,
                "altitude_m": request.location.altitude_m,
                "source": request.location.provider,
                "is_mock": request.platform_signals.is_mock,
                "is_simulated": request.platform_signals.is_simulated,
                "attestation_status": device.attestation_status,
                "risk_score": risk_score,
                "risk_reasons": json.dumps(risk_reasons),
                "purge_at": purge_at,
            },
        )

    # --------------------------------------------------------------- decision

    def _detect_ambiguity(
        self, candidates: list[VenueCandidate], accuracy_m: float
    ) -> tuple[bool, list[str]]:
        covering = [c for c in candidates if c.inside]
        if len(covering) >= 2:
            return True, ["multiple_polygons_cover_point"]
        if len(covering) == 1:
            primary = covering[0]
            for other in candidates:
                if other.id == primary.id:
                    continue
                if other.boundary_distance_m <= SHARED_BOUNDARY_EPSILON_M:
                    return True, ["shared_boundary_with_neighbor"]
                if other.boundary_distance_m <= accuracy_m:
                    return True, ["neighbor_within_accuracy_radius"]
        return False, []

    def _select_candidate(
        self,
        candidates: list[VenueCandidate],
        *,
        accuracy_m: float,
        hint: UUID | None,
    ) -> tuple[VenueCandidate | None, bool]:
        """Return (venue, inside). Falls back to the accuracy-aware entry buffer."""
        covering = [c for c in candidates if c.inside]
        if covering:
            return covering[0], True

        def in_entry_buffer(candidate: VenueCandidate) -> bool:
            # Accuracy widens the buffer, but never beyond what the venue is
            # willing to accept as a usable fix.
            slack = min(accuracy_m, candidate.max_gps_accuracy_m)
            return candidate.boundary_distance_m <= candidate.entry_buffer_m + slack

        eligible = [c for c in candidates if in_entry_buffer(c)]
        if not eligible:
            return None, False
        if hint is not None:
            hinted = next((c for c in eligible if c.id == hint), None)
            if hinted is not None:
                return hinted, False
        return eligible[0], False

    @staticmethod
    def _dwell_satisfied(
        samples: list[PresenceSample],
        *,
        venue_id: UUID,
        received_at: datetime,
        dwell_seconds: int,
        verdict: SampleVerdict,
    ) -> bool:
        matching = [s for s in samples if s.venue_id == str(venue_id) and s.verdict == verdict]
        if not matching:
            return False
        earliest = min(s.server_received_at for s in matching)
        return (received_at - earliest).total_seconds() >= dwell_seconds

    @staticmethod
    def _exit_dwell_satisfied(
        samples: list[PresenceSample],
        *,
        venue_id: UUID,
        received_at: datetime,
        exit_dwell_seconds: int,
    ) -> bool:
        matching = [s for s in samples if s.venue_id == str(venue_id) and s.credible_outside]
        if not matching:
            return False
        earliest = min(s.server_received_at for s in matching)
        return (received_at - earliest).total_seconds() >= exit_dwell_seconds

    # ---------------------------------------------------------------- process

    async def process_evidence(
        self,
        *,
        user: User,
        device: UserDevice,
        request: EvidenceRequest,
        received_at: datetime,
        allow_simulated: bool = False,
    ) -> PresenceData:
        if device.user_id != user.id:
            raise AppError(
                "DEVICE_NOT_OWNED",
                "This device is not registered to the authenticated account.",
                status_code=403,
            )
        if device.revoked_at is not None:
            raise AppError("DEVICE_REVOKED", "This device has been revoked.", status_code=403)

        await self._rate_limiter.check(user_id=user.id, device_id=device.id, now=received_at)

        age_seconds = (received_at - request.observed_at).total_seconds()
        if age_seconds > self._settings.max_evidence_age_seconds:
            return self._rejected("stale_evidence")
        if age_seconds < -self._settings.max_observed_future_skew_seconds:
            return self._rejected("observed_at_in_future")

        signals = request.platform_signals
        if (signals.is_mock or signals.is_simulated) and not allow_simulated:
            await self._persist_evidence(
                user=user,
                device=device,
                request=request,
                received_at=received_at,
                check_in_id=None,
                venue_timezone=None,
                risk_score=100,
                risk_reasons=["mock_location_flag"],
            )
            await self._session.commit()
            logger.warning(
                "presence_mock_location_rejected",
                user_id=str(user.id),
                device_id=str(device.id),
            )
            return self._rejected("mock_location")

        decision = await self._decide(user=user, request=request, received_at=received_at)
        return await self._apply(
            user=user,
            device=device,
            request=request,
            received_at=received_at,
            decision=decision,
        )

    def _rejected(self, reason: str) -> PresenceData:
        return PresenceData(
            state="rejected",
            decision="reject",
            reasons=[reason],
            social_features_enabled=False,
        )

    async def _decide(
        self,
        *,
        user: User,
        request: EvidenceRequest,
        received_at: datetime,
    ) -> Decision:
        accuracy = request.location.horizontal_accuracy_m
        candidates = await find_candidates(
            self._session,
            request.location.latitude,
            request.location.longitude,
            float(self._settings.presence_candidate_radius_m),
        )
        active = await self.load_active_check_in(user.id, for_update=True)

        exit_view: VenueCandidate | None = None
        if active is not None:
            exit_view = next((c for c in candidates if c.id == active.venue_id), None)
            if exit_view is None:
                exit_view = await describe_venue_for_point(
                    self._session,
                    active.venue_id,
                    request.location.latitude,
                    request.location.longitude,
                )

        credible_outside = (
            exit_view is not None
            and not exit_view.inside
            and (exit_view.boundary_distance_m - accuracy) > exit_view.exit_buffer_m
        )

        prior_samples = await self._safe_recent_samples(user.id)
        ambiguous, ambiguity_reasons = self._detect_ambiguity(candidates, accuracy)

        if ambiguous:
            # Never open a check-in during ambiguity. If one is already open we
            # degrade it in place; picking one of the overlapping venues would
            # be a guess with social consequences.
            venue: VenueCandidate | None
            durable_state: str | None
            if active is not None and exit_view is not None:
                venue = exit_view
                durable_state = "degraded"
            else:
                venue = next((c for c in candidates if c.inside), None)
                durable_state = None
            return Decision(
                state="ambiguous",
                decision="ambiguous_venue",
                reasons=ambiguity_reasons,
                venue=venue,
                durable_state=durable_state,
                verification_level=None,
                confidence=_confidence_score(
                    inside=True,
                    accuracy_ok=True,
                    dwell_ok=False,
                    ambiguous=True,
                    in_entry_buffer=False,
                ),
                sample_verdict="ambiguous",
                credible_outside=credible_outside,
                persist_evidence=True,
                risk_score=40,
            )

        selected, inside = self._select_candidate(
            candidates, accuracy_m=accuracy, hint=request.candidate_venue_id
        )

        # No usable venue: either hold position or run exit hysteresis.
        if selected is None:
            return self._decide_outside(
                active=active,
                exit_view=exit_view,
                credible_outside=credible_outside,
                prior_samples=prior_samples,
                received_at=received_at,
            )

        accuracy_ok = accuracy <= selected.max_gps_accuracy_m
        verdict: SampleVerdict = "inside" if inside and accuracy_ok else "provisional_buffer"

        already_here = (
            active is not None
            and active.venue_id == selected.id
            and active.state in {"verified", "degraded"}
        )
        dwell_ok = already_here or self._dwell_satisfied(
            prior_samples,
            venue_id=selected.id,
            received_at=received_at,
            dwell_seconds=selected.entry_dwell_seconds,
            verdict="inside",
        )

        reasons: list[str] = []
        if inside and accuracy_ok and dwell_ok:
            state: PresenceState = "verified"
            durable = "verified"
            level = "standard"
            decision_code = "verified"
        elif already_here and active is not None:
            # An established check-in is not downgraded by one weak sample. The
            # lease keeps its own expiry, which this sample does not extend, and
            # the aggregator enforces it.
            return Decision(
                state=self._response_state(active.state),
                decision="hold",
                reasons=[
                    "accuracy_exceeds_venue_maximum"
                    if inside
                    else "outside_polygon_within_entry_buffer"
                ],
                venue=selected,
                durable_state=None,
                verification_level=active.verification_level,
                confidence=active.confidence_score,
                sample_verdict=verdict,
                credible_outside=credible_outside,
            )
        else:
            state = "provisional"
            durable = "provisional"
            level = "weak"
            decision_code = "provisional"
            if inside and not accuracy_ok:
                reasons.append("accuracy_exceeds_venue_maximum")
            if inside and accuracy_ok and not dwell_ok:
                reasons.append("entry_dwell_not_met")
            if not inside:
                reasons.append("outside_polygon_within_entry_buffer")

        # Moving to a different venue requires clearing exit hysteresis on the
        # current one first; otherwise the old check-in would be abandoned on a
        # single sample.
        if active is not None and active.venue_id != selected.id:
            exit_ok = credible_outside and self._exit_dwell_satisfied(
                prior_samples,
                venue_id=active.venue_id,
                received_at=received_at,
                exit_dwell_seconds=(exit_view.exit_dwell_seconds if exit_view is not None else 30),
            )
            if not exit_ok:
                return Decision(
                    state=self._response_state(active.state),
                    decision="hold",
                    reasons=["pending_exit_dwell_at_current_venue"],
                    venue=exit_view,
                    durable_state=None,
                    verification_level=active.verification_level,
                    confidence=active.confidence_score,
                    sample_verdict="outside" if credible_outside else "provisional_buffer",
                    credible_outside=credible_outside,
                )

        return Decision(
            state=state,
            decision=decision_code,
            reasons=reasons,
            venue=selected,
            durable_state=durable,
            exit_active=active is not None and active.venue_id != selected.id,
            exit_reason="venue_change" if active is not None else None,
            verification_level=level,
            confidence=_confidence_score(
                inside=inside,
                accuracy_ok=accuracy_ok,
                dwell_ok=dwell_ok,
                ambiguous=False,
                in_entry_buffer=not inside,
            ),
            sample_verdict=verdict,
            credible_outside=credible_outside,
            persist_evidence=(active is None or active.state != durable or state == "verified"),
            risk_score=0 if accuracy_ok else 25,
        )

    def _decide_outside(
        self,
        *,
        active: CheckIn | None,
        exit_view: VenueCandidate | None,
        credible_outside: bool,
        prior_samples: list[PresenceSample],
        received_at: datetime,
    ) -> Decision:
        if active is None:
            return Decision(
                state="outside",
                decision="outside",
                reasons=["no_candidate_venue"],
                sample_verdict="outside",
            )
        exit_dwell = exit_view.exit_dwell_seconds if exit_view is not None else 30
        exit_ok = credible_outside and self._exit_dwell_satisfied(
            prior_samples,
            venue_id=active.venue_id,
            received_at=received_at,
            exit_dwell_seconds=exit_dwell,
        )
        if exit_ok:
            return Decision(
                state="exited",
                decision="exit",
                reasons=["exit_dwell_satisfied"],
                venue=exit_view,
                durable_state="exited",
                exit_active=True,
                exit_reason="geofence_exit",
                sample_verdict="outside",
                credible_outside=True,
                persist_evidence=True,
            )
        return Decision(
            state=self._response_state(active.state),
            decision="hold",
            reasons=["outside_pending_exit_dwell" if credible_outside else "outside_exit_buffer"],
            venue=exit_view,
            verification_level=active.verification_level,
            confidence=active.confidence_score,
            sample_verdict="outside" if credible_outside else "provisional_buffer",
            credible_outside=credible_outside,
        )

    @staticmethod
    def _response_state(durable_state: str) -> PresenceState:
        if durable_state in {"provisional", "verified", "degraded"}:
            return durable_state  # type: ignore[return-value]
        return "outside"

    async def _safe_recent_samples(self, user_id: UUID) -> list[PresenceSample]:
        try:
            return await self._samples.recent(user_id)
        except RedisError:
            logger.error("presence_sample_buffer_unavailable", user_id=str(user_id))
            return []

    # ------------------------------------------------------------ persistence

    async def _apply(
        self,
        *,
        user: User,
        device: UserDevice,
        request: EvidenceRequest,
        received_at: datetime,
        decision: Decision,
    ) -> PresenceData:
        ghost, discoverable, allow_cards = self._privacy_flags(user)
        active = await self.load_active_check_in(user.id, for_update=True)
        previous_venue_id = active.venue_id if active is not None else None

        verified_until: datetime | None = None
        grace_until: datetime | None = None
        check_in: CheckIn | None = None

        if decision.durable_state == "verified":
            verified_until = received_at + timedelta(seconds=self._settings.verified_lease_seconds)
            grace_until = verified_until + timedelta(seconds=self._settings.degraded_grace_seconds)
        elif decision.durable_state == "provisional":
            grace_until = received_at + timedelta(seconds=self._settings.verified_lease_seconds)
        elif decision.durable_state == "degraded":
            # Degrading must never buy more wall-clock time than the original
            # verified lease already granted.
            grace_until = (
                active.grace_until
                if active is not None and active.grace_until is not None
                else received_at + timedelta(seconds=self._settings.degraded_grace_seconds)
            )

        state_changed = False
        try:
            if decision.exit_active and active is not None:
                self._close_check_in(
                    active,
                    received_at=received_at,
                    reason=decision.exit_reason or "geofence_exit",
                )
                self._emit(event_type="presence.exited", check_in=active, occurred_at=received_at)
                # Flush the exit UPDATE before any new INSERT: the unit of work
                # emits inserts first by default, which would collide with the
                # one-active-check-in-per-user partial unique index.
                await self._session.flush()
                state_changed = True
                active = None

            if decision.durable_state in DURABLE_STATES and decision.venue is not None:
                check_in, state_changed_now = self._upsert_check_in(
                    user=user,
                    active=active,
                    decision=decision,
                    received_at=received_at,
                    verified_until=verified_until,
                    grace_until=grace_until,
                    ghost=ghost,
                    discoverable=discoverable,
                )
                state_changed = state_changed or state_changed_now
            elif decision.durable_state is None and active is not None:
                check_in = active
                verified_until = active.verified_until
                grace_until = active.grace_until

            if decision.persist_evidence or state_changed:
                # Raw SQL does not autoflush, and the evidence row carries an FK
                # to a check-in that may still be pending in the unit of work.
                await self._session.flush()
                await self._persist_evidence(
                    user=user,
                    device=device,
                    request=request,
                    received_at=received_at,
                    check_in_id=check_in.id if check_in is not None else None,
                    venue_timezone=decision.venue.timezone if decision.venue else None,
                    risk_score=decision.risk_score,
                    risk_reasons=list(decision.reasons),
                )
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise AppError(
                "PRESENCE_CONFLICT",
                "Concurrent presence update; retry with fresh evidence.",
                status_code=409,
            ) from exc

        valkey_ok = await self._sync_valkey(
            user=user,
            request=request,
            received_at=received_at,
            decision=decision,
            check_in=check_in,
            verified_until=verified_until,
            grace_until=grace_until,
            ghost=ghost,
            discoverable=discoverable,
            previous_venue_id=previous_venue_id,
        )

        lease_expires_at: datetime | None = None
        if decision.state == "verified":
            lease_expires_at = verified_until
        elif decision.state in {"provisional", "degraded"}:
            lease_expires_at = grace_until

        social_enabled = (
            decision.state == "verified"
            and valkey_ok
            and not ghost
            and discoverable
            and allow_cards
            and self._account_active(user)
        )
        reasons = list(decision.reasons)
        if decision.state == "verified" and not valkey_ok:
            reasons.append("presence_cache_unavailable")

        venue_payload = None
        if decision.venue is not None and decision.state != "outside":
            venue_payload = PresenceVenue(id=decision.venue.id, name=decision.venue.name)

        level = (
            decision.verification_level if decision.state in {"verified", "provisional"} else None
        )
        return PresenceData(
            state=decision.state,
            venue=venue_payload,
            verification_level=level,  # type: ignore[arg-type]
            lease_expires_at=lease_expires_at if valkey_ok else None,
            social_features_enabled=social_enabled,
            decision=decision.decision,
            reasons=reasons,
        )

    def _close_check_in(self, check_in: CheckIn, *, received_at: datetime, reason: str) -> None:
        check_in.state = "exited"
        check_in.exited_at = received_at
        check_in.exit_reason = reason
        check_in.updated_at = received_at

    def _upsert_check_in(
        self,
        *,
        user: User,
        active: CheckIn | None,
        decision: Decision,
        received_at: datetime,
        verified_until: datetime | None,
        grace_until: datetime | None,
        ghost: bool,
        discoverable: bool,
    ) -> tuple[CheckIn, bool]:
        assert decision.venue is not None
        assert decision.durable_state is not None
        lease_expires_at = grace_until or received_at
        verification_level = decision.verification_level or "weak"

        if active is not None and active.venue_id == decision.venue.id:
            changed = active.state != decision.durable_state
            active.state = decision.durable_state
            active.verification_level = verification_level
            active.confidence_score = decision.confidence
            active.geofence_version = decision.venue.geofence_version
            active.ghost_mode_snapshot = ghost
            active.discoverable_snapshot = discoverable
            active.verified_until = verified_until
            active.grace_until = grace_until
            active.lease_expires_at = lease_expires_at
            active.updated_at = received_at
            if decision.durable_state == "verified":
                active.last_verified_at = received_at
                if active.verified_at is None:
                    active.verified_at = received_at
            if changed:
                self._emit(
                    event_type=f"presence.{decision.durable_state}",
                    check_in=active,
                    occurred_at=received_at,
                )
            return active, changed

        check_in = CheckIn(
            # Assigned client-side so the outbox event and the Valkey lease can
            # reference the check-in before the INSERT is flushed.
            id=uuid4(),
            user_id=user.id,
            venue_id=decision.venue.id,
            state=decision.durable_state,
            verification_level=verification_level,
            confidence_score=decision.confidence,
            entry_method="fused_location",
            ghost_mode_snapshot=ghost,
            discoverable_snapshot=discoverable,
            entered_at=received_at,
            verified_at=received_at if decision.durable_state == "verified" else None,
            last_verified_at=received_at if decision.durable_state == "verified" else None,
            verified_until=verified_until,
            grace_until=grace_until,
            lease_expires_at=lease_expires_at,
            geofence_version=decision.venue.geofence_version,
            risk_reasons=[],
            created_at=received_at,
            updated_at=received_at,
        )
        self._session.add(check_in)
        self._emit(event_type="presence.entered", check_in=check_in, occurred_at=received_at)
        if decision.durable_state == "verified":
            self._emit(event_type="presence.verified", check_in=check_in, occurred_at=received_at)
        return check_in, True

    async def _sync_valkey(
        self,
        *,
        user: User,
        request: EvidenceRequest,
        received_at: datetime,
        decision: Decision,
        check_in: CheckIn | None,
        verified_until: datetime | None,
        grace_until: datetime | None,
        ghost: bool,
        discoverable: bool,
        previous_venue_id: UUID | None,
    ) -> bool:
        """Best-effort cache sync. Returns False when the lease is not live."""
        try:
            await self._record_samples(
                user_id=user.id,
                request=request,
                received_at=received_at,
                decision=decision,
                previous_venue_id=previous_venue_id,
            )
            if decision.state in {"exited"} or decision.durable_state == "exited":
                await self._leases.clear(user.id, venue_id=previous_venue_id)
                return True
            if check_in is None or decision.durable_state is None or decision.venue is None:
                return True
            effective_grace = grace_until or received_at
            await self._leases.update(
                LeaseWrite(
                    user_id=user.id,
                    venue_id=decision.venue.id,
                    check_in_id=check_in.id,
                    state=decision.durable_state,
                    confidence=decision.confidence,
                    verification_level=decision.verification_level or "weak",
                    ghost_mode=ghost,
                    discoverable=discoverable,
                    verified_until=verified_until or effective_grace,
                    grace_until=effective_grace,
                    lease_version=decision.venue.geofence_version,
                    previous_venue_id=previous_venue_id,
                )
            )
            return True
        except RedisError:
            logger.error(
                "presence_lease_write_failed",
                user_id=str(user.id),
                state=decision.state,
            )
            return False

    async def _record_samples(
        self,
        *,
        user_id: UUID,
        request: EvidenceRequest,
        received_at: datetime,
        decision: Decision,
        previous_venue_id: UUID | None,
    ) -> None:
        observed = request.observed_at.astimezone(UTC)
        selected_id = decision.venue.id if decision.venue is not None else None
        # A sample with no venue teaches the buffer nothing; dwell and exit
        # windows are always per venue.
        if decision.venue is not None and selected_id is not None:
            await self._samples.push(
                user_id,
                PresenceSample(
                    server_received_at=received_at,
                    observed_at=observed,
                    client_sequence=request.client_sequence,
                    venue_id=str(selected_id),
                    verdict=decision.sample_verdict,
                    accuracy_m=request.location.horizontal_accuracy_m,
                    boundary_distance_m=decision.venue.boundary_distance_m,
                    geofence_version=decision.venue.geofence_version,
                    credible_outside=(
                        decision.credible_outside and selected_id == previous_venue_id
                    ),
                ),
            )
        # The exit clock belongs to the venue we are leaving, which is not always
        # the venue this sample selected.
        if previous_venue_id is not None and previous_venue_id != selected_id:
            await self._samples.push(
                user_id,
                PresenceSample(
                    server_received_at=received_at,
                    observed_at=observed,
                    client_sequence=request.client_sequence,
                    venue_id=str(previous_venue_id),
                    verdict="outside" if decision.credible_outside else "provisional_buffer",
                    accuracy_m=request.location.horizontal_accuracy_m,
                    boundary_distance_m=None,
                    geofence_version=None,
                    credible_outside=decision.credible_outside,
                ),
            )
