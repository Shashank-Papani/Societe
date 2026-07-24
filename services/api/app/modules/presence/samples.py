"""Short-lived dwell/hysteresis buffer in Valkey.

Only the derived verdict is stored. Latitude/longitude never enter this buffer,
so a Valkey dump cannot reconstruct a movement trace.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from app.modules.presence.schemas import SampleVerdict


@dataclass(frozen=True)
class PresenceSample:
    server_received_at: datetime
    observed_at: datetime
    client_sequence: int
    venue_id: str | None
    verdict: SampleVerdict
    accuracy_m: float
    boundary_distance_m: float | None
    geofence_version: int | None
    credible_outside: bool

    def to_json(self) -> str:
        return json.dumps(
            {
                "server_received_at": self.server_received_at.isoformat(),
                "observed_at": self.observed_at.isoformat(),
                "client_sequence": self.client_sequence,
                "venue_id": self.venue_id,
                "verdict": self.verdict,
                "accuracy_m": self.accuracy_m,
                "boundary_distance_m": self.boundary_distance_m,
                "geofence_version": self.geofence_version,
                "credible_outside": self.credible_outside,
            },
            separators=(",", ":"),
        )


def _parse_datetime(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _parse_sample(raw: str) -> PresenceSample | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    received_at = _parse_datetime(payload.get("server_received_at"))
    observed_at = _parse_datetime(payload.get("observed_at"))
    verdict = payload.get("verdict")
    if received_at is None or observed_at is None:
        return None
    if verdict not in {"inside", "outside", "ambiguous", "provisional_buffer"}:
        return None
    boundary_distance = payload.get("boundary_distance_m")
    geofence_version = payload.get("geofence_version")
    venue_id = payload.get("venue_id")
    return PresenceSample(
        server_received_at=received_at,
        observed_at=observed_at,
        client_sequence=int(payload.get("client_sequence", 0)),
        venue_id=str(venue_id) if venue_id is not None else None,
        verdict=verdict,
        accuracy_m=float(payload.get("accuracy_m", 0.0)),
        boundary_distance_m=None if boundary_distance is None else float(boundary_distance),
        geofence_version=None if geofence_version is None else int(geofence_version),
        credible_outside=bool(payload.get("credible_outside", False)),
    )


class SampleBuffer:
    def __init__(
        self,
        redis: Redis[str],
        *,
        max_samples: int = 12,
        ttl_seconds: int = 120,
    ) -> None:
        self._redis = redis
        self._max = max_samples
        self._ttl = ttl_seconds

    def key(self, user_id: UUID | str) -> str:
        return f"presence:user:{user_id}:samples"

    async def recent(self, user_id: UUID | str) -> list[PresenceSample]:
        """Newest first."""
        raw_items = await self._redis.lrange(self.key(user_id), 0, self._max - 1)
        samples = [_parse_sample(raw) for raw in raw_items]
        return [sample for sample in samples if sample is not None]

    async def push(self, user_id: UUID | str, sample: PresenceSample) -> None:
        key = self.key(user_id)
        pipe = self._redis.pipeline()
        pipe.lpush(key, sample.to_json())
        pipe.ltrim(key, 0, self._max - 1)
        pipe.expire(key, self._ttl)
        await pipe.execute()

    async def clear(self, user_id: UUID | str) -> None:
        await self._redis.delete(self.key(user_id))
