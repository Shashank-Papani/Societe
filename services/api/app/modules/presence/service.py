"""Presence orchestration: evidence, current state, leave, and lease expiry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import CheckIn, OutboxEvent, User, UserDevice
from app.modules.presence.engine import PresenceEngine
from app.modules.presence.geospatial import get_venue_name
from app.modules.presence.leases import PresenceLeaseStore
from app.modules.presence.samples import SampleBuffer
from app.modules.presence.schemas import (
    EvidenceRequest,
    PresenceData,
    PresenceState,
    PresenceVenue,
)

logger = get_logger(__name__)

DEGRADE_SQL = """
WITH due AS (
    SELECT id
    FROM app.check_ins
    WHERE state = 'verified'
      AND verified_until IS NOT NULL
      AND verified_until <= now()
    ORDER BY verified_until
    FOR UPDATE SKIP LOCKED
    LIMIT :limit
)
UPDATE app.check_ins c
SET state = 'degraded', updated_at = now()
FROM due
WHERE c.id = due.id
RETURNING c.id, c.user_id, c.venue_id, c.verification_level
"""

EXPIRE_SQL = """
WITH due AS (
    SELECT id
    FROM app.check_ins
    WHERE state IN ('provisional', 'verified', 'degraded')
      AND grace_until IS NOT NULL
      AND grace_until <= now()
    ORDER BY grace_until
    FOR UPDATE SKIP LOCKED
    LIMIT :limit
)
UPDATE app.check_ins c
SET state = 'exited',
    exited_at = now(),
    exit_reason = 'lease_expired',
    updated_at = now()
FROM due
WHERE c.id = due.id
RETURNING c.id, c.user_id, c.venue_id, c.verification_level
"""

PURGE_EVIDENCE_SQL = """
DELETE FROM ephemeral.location_evidence e
USING (
    SELECT id, purge_at
    FROM ephemeral.location_evidence
    WHERE purge_at < now()
    LIMIT :limit
) due
WHERE e.id = due.id AND e.purge_at = due.purge_at
"""


@dataclass(frozen=True)
class ExpireResult:
    degraded: int
    exited: int


class PresenceService:
    def __init__(self, session: AsyncSession, redis: Redis[str], settings: Settings) -> None:
        self._session = session
        self._redis = redis
        self._settings = settings
        self._engine = PresenceEngine(session, redis, settings)
        self._leases = PresenceLeaseStore(redis)
        self._samples = SampleBuffer(
            redis,
            max_samples=settings.presence_sample_buffer_max,
            ttl_seconds=settings.presence_sample_buffer_ttl_seconds,
        )

    async def submit_evidence(
        self,
        *,
        user: User,
        request: EvidenceRequest,
        received_at: datetime,
        allow_simulated: bool = False,
    ) -> PresenceData:
        device = await self._load_device(user, request.device_id)
        return await self._engine.process_evidence(
            user=user,
            device=device,
            request=request,
            received_at=received_at,
            allow_simulated=allow_simulated,
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
        return device

    async def get_me(self, user: User, *, now: datetime | None = None) -> PresenceData:
        moment = now or datetime.now(UTC)
        active = await self._engine.load_active_check_in(user.id)

        try:
            lease = await self._leases.read(user.id)
            cache_ok = True
        except RedisError:
            logger.error("presence_lease_read_failed", user_id=str(user.id))
            lease = None
            cache_ok = False

        if lease is None:
            # A durable check-in without a lease is not presence. Ask the client
            # to re-prove rather than inferring location from an old row.
            if active is not None:
                venue_name = await get_venue_name(self._session, active.venue_id)
                return PresenceData(
                    state="refresh_required",
                    venue=PresenceVenue(id=active.venue_id, name=venue_name or "Unknown venue"),
                    verification_level=None,
                    lease_expires_at=None,
                    social_features_enabled=False,
                    decision="refresh_required",
                    reasons=["presence_cache_miss" if cache_ok else "presence_cache_unavailable"],
                )
            return PresenceData(
                state="outside",
                decision="outside",
                reasons=[] if cache_ok else ["presence_cache_unavailable"],
            )

        state: PresenceState
        lease_expires_at: datetime | None
        if lease.state == "verified" and moment < lease.verified_until:
            state = "verified"
            lease_expires_at = lease.verified_until
        elif lease.state == "provisional" and moment < lease.grace_until:
            state = "provisional"
            lease_expires_at = lease.grace_until
        elif moment < lease.grace_until:
            state = "degraded"
            lease_expires_at = lease.grace_until
        elif active is not None:
            state = "refresh_required"
            lease_expires_at = None
        else:
            state = "outside"
            lease_expires_at = None

        venue_name = await get_venue_name(self._session, lease.venue_id)
        ghost = lease.ghost_mode
        social = (
            state == "verified"
            and not ghost
            and lease.discoverable
            and self._allow_calling_cards(user)
            and user.account_status == "active"
            and user.deleted_at is None
        )
        level = lease.verification_level if state in {"verified", "provisional"} else None
        return PresenceData(
            state=state,
            venue=(
                PresenceVenue(id=lease.venue_id, name=venue_name or "Unknown venue")
                if state != "outside"
                else None
            ),
            verification_level=level if level in {"weak", "standard"} else None,  # type: ignore[arg-type]
            lease_expires_at=lease_expires_at,
            social_features_enabled=social,
            decision="current",
            reasons=[],
        )

    @staticmethod
    def _allow_calling_cards(user: User) -> bool:
        privacy = user.privacy
        if privacy is None:
            return False
        return False if privacy.ghost_mode else privacy.allow_calling_cards

    async def leave(self, user: User, *, received_at: datetime) -> PresenceData:
        active = await self._engine.load_active_check_in(user.id, for_update=True)
        venue_id: UUID | None = None
        venue_name: str | None = None

        if active is not None:
            venue_id = active.venue_id
            active.state = "exited"
            active.exited_at = received_at
            active.exit_reason = "user_left"
            active.updated_at = received_at
            self._session.add(
                OutboxEvent(
                    aggregate_type="check_in",
                    aggregate_id=active.id,
                    event_type="presence.exited",
                    payload={
                        "user_id": str(active.user_id),
                        "venue_id": str(active.venue_id),
                        "check_in_id": str(active.id),
                        "state": "exited",
                        "exit_reason": "user_left",
                        "occurred_at": received_at.isoformat(),
                    },
                    occurred_at=received_at,
                    available_at=received_at,
                )
            )
            await self._session.commit()
            venue_name = await get_venue_name(self._session, venue_id)

        try:
            await self._leases.clear(user.id, venue_id=venue_id)
            await self._samples.clear(user.id)
        except RedisError:
            logger.error("presence_lease_clear_failed", user_id=str(user.id))

        if active is None:
            return PresenceData(
                state="outside",
                decision="leave",
                reasons=["no_active_check_in"],
            )
        return PresenceData(
            state="exited",
            venue=(
                PresenceVenue(id=venue_id, name=venue_name or "Unknown venue")
                if venue_id is not None
                else None
            ),
            decision="leave",
            reasons=[],
        )

    async def expire_batch(self, *, limit: int = 200) -> ExpireResult:
        """Advance verified → degraded → exited for leases past their deadline."""
        degraded_result = await self._session.execute(text(DEGRADE_SQL), {"limit": limit})
        degraded_rows = degraded_result.mappings().all()
        for row in degraded_rows:
            self._session.add(
                OutboxEvent(
                    aggregate_type="check_in",
                    aggregate_id=row["id"],
                    event_type="presence.degraded",
                    payload={
                        "user_id": str(row["user_id"]),
                        "venue_id": str(row["venue_id"]),
                        "check_in_id": str(row["id"]),
                        "state": "degraded",
                        "verification_level": row["verification_level"],
                    },
                )
            )

        exited_result = await self._session.execute(text(EXPIRE_SQL), {"limit": limit})
        exited_rows = exited_result.mappings().all()
        for row in exited_rows:
            self._session.add(
                OutboxEvent(
                    aggregate_type="check_in",
                    aggregate_id=row["id"],
                    event_type="presence.exited",
                    payload={
                        "user_id": str(row["user_id"]),
                        "venue_id": str(row["venue_id"]),
                        "check_in_id": str(row["id"]),
                        "state": "exited",
                        "exit_reason": "lease_expired",
                    },
                )
            )
        await self._session.commit()

        for row in exited_rows:
            try:
                await self._leases.clear(row["user_id"], venue_id=row["venue_id"])
                await self._samples.clear(row["user_id"])
            except RedisError:
                logger.error("presence_expiry_cache_clear_failed", check_in_id=str(row["id"]))

        return ExpireResult(degraded=len(degraded_rows), exited=len(exited_rows))

    async def purge_expired_evidence(self, *, limit: int = 5_000) -> int:
        result = await self._session.execute(text(PURGE_EVIDENCE_SQL), {"limit": limit})
        deleted = getattr(result, "rowcount", 0) or 0
        await self._session.commit()
        return int(deleted)

    async def active_check_in(self, user_id: UUID) -> CheckIn | None:
        return await self._engine.load_active_check_in(user_id)
