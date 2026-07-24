"""Valkey presence lease store.

The lease is the authorization artifact: durable check-in rows describe history,
but only a live lease enables social features. Every mutation is atomic so a
venue transition can never leave a user in two venue sets at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from redis.asyncio import Redis
from redis.commands.core import AsyncScript

LEASE_EXPIRATIONS_KEY = "presence:lease_expirations"

_LUA_DIR = Path(__file__).resolve().parent / "lua"


def _load_script(name: str) -> str:
    return (_LUA_DIR / name).read_text(encoding="utf-8")


def user_key(user_id: UUID | str) -> str:
    return f"presence:user:{user_id}"


def venue_active_key(venue_id: UUID | str) -> str:
    return f"presence:venue:{venue_id}:active"


def venue_discoverable_key(venue_id: UUID | str) -> str:
    return f"presence:venue:{venue_id}:discoverable"


@dataclass(frozen=True)
class LeaseWrite:
    user_id: UUID
    venue_id: UUID
    check_in_id: UUID
    state: str
    confidence: int
    verification_level: str
    ghost_mode: bool
    discoverable: bool
    verified_until: datetime
    grace_until: datetime
    lease_version: int
    previous_venue_id: UUID | None = None


@dataclass(frozen=True)
class LeaseSnapshot:
    user_id: UUID
    venue_id: UUID
    check_in_id: UUID | None
    state: str
    confidence: int
    verification_level: str | None
    ghost_mode: bool
    discoverable: bool
    verified_until: datetime
    grace_until: datetime
    lease_version: int


def _epoch(value: datetime) -> int:
    return int(value.timestamp())


def _from_epoch(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (TypeError, ValueError):
        return None


class PresenceLeaseStore:
    def __init__(self, redis: Redis[str]) -> None:
        self._redis = redis
        self._update: AsyncScript = redis.register_script(_load_script("update_lease.lua"))

    async def update(self, write: LeaseWrite) -> tuple[str | None, str | None]:
        """Write the lease atomically. Returns (prior_venue_id, prior_state)."""
        new_active = venue_active_key(write.venue_id)
        new_discoverable = venue_discoverable_key(write.venue_id)
        prior_venue = write.previous_venue_id or write.venue_id
        old_active = venue_active_key(prior_venue)
        old_discoverable = venue_discoverable_key(prior_venue)

        verified_until_epoch = _epoch(write.verified_until)
        grace_until_epoch = _epoch(write.grace_until)
        # The expiration index points at the *next* state transition so the
        # aggregator wakes for degradation before it wakes for the exit.
        next_transition = verified_until_epoch if write.state == "verified" else grace_until_epoch
        # Keep the hash readable through the whole grace window plus a small
        # cushion, otherwise GET /presence/me loses the degraded state early.
        hash_ttl = max(grace_until_epoch - int(datetime.now(UTC).timestamp()), 1) + 30

        raw = await self._update(
            keys=[
                user_key(write.user_id),
                new_active,
                new_discoverable,
                old_active,
                old_discoverable,
                LEASE_EXPIRATIONS_KEY,
            ],
            args=[
                str(write.venue_id),
                str(write.check_in_id),
                write.state,
                str(write.confidence),
                write.verification_level,
                "true" if write.ghost_mode else "false",
                "true" if write.discoverable else "false",
                str(verified_until_epoch),
                str(grace_until_epoch),
                str(hash_ttl),
                str(write.user_id),
                str(write.lease_version),
                str(next_transition),
            ],
        )
        result = cast(list[Any], raw or [])
        prior_venue_id = str(result[0]) if len(result) > 0 and result[0] else None
        prior_state = str(result[1]) if len(result) > 1 and result[1] else None
        return prior_venue_id, prior_state

    async def read(self, user_id: UUID) -> LeaseSnapshot | None:
        raw = await self._redis.hgetall(user_key(user_id))
        if not raw:
            return None
        venue_raw = raw.get("venue_id")
        verified_until = _from_epoch(raw.get("verified_until_epoch"))
        grace_until = _from_epoch(raw.get("grace_until_epoch"))
        if not venue_raw or verified_until is None or grace_until is None:
            return None
        check_in_raw = raw.get("check_in_id")
        try:
            venue_id = UUID(venue_raw)
            check_in_id = UUID(check_in_raw) if check_in_raw else None
        except ValueError:
            return None
        return LeaseSnapshot(
            user_id=user_id,
            venue_id=venue_id,
            check_in_id=check_in_id,
            state=raw.get("state", "outside"),
            confidence=int(raw.get("confidence", 0) or 0),
            verification_level=raw.get("verification_level") or None,
            ghost_mode=raw.get("ghost_mode") == "true",
            discoverable=raw.get("discoverable") == "true",
            verified_until=verified_until,
            grace_until=grace_until,
            lease_version=int(raw.get("lease_version", 0) or 0),
        )

    async def clear(self, user_id: UUID, *, venue_id: UUID | None = None) -> None:
        """Drop the lease and every membership derived from it."""
        target = venue_id
        if target is None:
            existing = await self._redis.hget(user_key(user_id), "venue_id")
            if existing:
                try:
                    target = UUID(existing)
                except ValueError:
                    target = None
        pipe = self._redis.pipeline()
        if target is not None:
            pipe.zrem(venue_active_key(target), str(user_id))
            pipe.zrem(venue_discoverable_key(target), str(user_id))
        pipe.zrem(LEASE_EXPIRATIONS_KEY, str(user_id))
        pipe.delete(user_key(user_id))
        await pipe.execute()

    async def due_user_ids(self, *, now: datetime, limit: int) -> list[str]:
        """User IDs whose next lease transition is due (oldest first)."""
        return list(
            await self._redis.zrangebyscore(
                LEASE_EXPIRATIONS_KEY,
                min="-inf",
                max=_epoch(now),
                start=0,
                num=limit,
            )
        )
