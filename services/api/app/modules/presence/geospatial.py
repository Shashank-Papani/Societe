"""PostGIS candidate resolution for presence.

Candidates are selected by distance to the *boundary*, not the centroid: a large
irregular venue can cover a point that sits well over the candidate radius away
from its centroid, and a centroid-only prefilter would silently drop it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

CANDIDATE_LIMIT = 25

_CANDIDATE_SQL = """
WITH sample AS (
    SELECT
        ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326) AS geom,
        ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography AS geog
)
SELECT
    v.id,
    v.name,
    v.timezone,
    v.geofence_version,
    v.max_gps_accuracy_m,
    v.entry_dwell_seconds,
    v.exit_dwell_seconds,
    v.entry_buffer_m,
    v.exit_buffer_m,
    ST_Covers(v.boundary, sample.geom) AS inside,
    ST_Distance(v.boundary::geography, sample.geog) AS boundary_distance_m,
    ST_Distance(v.centroid, sample.geog) AS centroid_distance_m,
    ST_Area(v.boundary::geography) AS polygon_area_m2
FROM app.venues v
CROSS JOIN sample
WHERE v.status = 'active'
  AND ST_DWithin(v.boundary::geography, sample.geog, :radius_m)
ORDER BY
    inside DESC,
    boundary_distance_m ASC,
    polygon_area_m2 ASC,
    v.id ASC
LIMIT :limit
"""

_VENUE_BY_ID_SQL = """
WITH sample AS (
    SELECT
        ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326) AS geom,
        ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography AS geog
)
SELECT
    v.id,
    v.name,
    v.timezone,
    v.geofence_version,
    v.max_gps_accuracy_m,
    v.entry_dwell_seconds,
    v.exit_dwell_seconds,
    v.entry_buffer_m,
    v.exit_buffer_m,
    ST_Covers(v.boundary, sample.geom) AS inside,
    ST_Distance(v.boundary::geography, sample.geog) AS boundary_distance_m,
    ST_Distance(v.centroid, sample.geog) AS centroid_distance_m,
    ST_Area(v.boundary::geography) AS polygon_area_m2
FROM app.venues v
CROSS JOIN sample
WHERE v.id = CAST(:venue_id AS uuid)
"""


@dataclass(frozen=True)
class VenueCandidate:
    id: UUID
    name: str
    timezone: str
    geofence_version: int
    max_gps_accuracy_m: float
    entry_dwell_seconds: int
    exit_dwell_seconds: int
    entry_buffer_m: float
    exit_buffer_m: float
    inside: bool
    boundary_distance_m: float
    centroid_distance_m: float
    polygon_area_m2: float


def _row_to_candidate(row: Any) -> VenueCandidate:
    return VenueCandidate(
        id=row["id"],
        name=row["name"],
        timezone=row["timezone"],
        geofence_version=int(row["geofence_version"]),
        max_gps_accuracy_m=float(row["max_gps_accuracy_m"]),
        entry_dwell_seconds=int(row["entry_dwell_seconds"]),
        exit_dwell_seconds=int(row["exit_dwell_seconds"]),
        entry_buffer_m=float(row["entry_buffer_m"]),
        exit_buffer_m=float(row["exit_buffer_m"]),
        inside=bool(row["inside"]),
        boundary_distance_m=float(row["boundary_distance_m"]),
        centroid_distance_m=float(row["centroid_distance_m"]),
        polygon_area_m2=float(row["polygon_area_m2"]),
    )


async def find_candidates(
    session: AsyncSession,
    latitude: float,
    longitude: float,
    radius_m: float,
    *,
    limit: int = CANDIDATE_LIMIT,
) -> list[VenueCandidate]:
    result = await session.execute(
        text(_CANDIDATE_SQL),
        {
            "latitude": latitude,
            "longitude": longitude,
            "radius_m": radius_m,
            "limit": limit,
        },
    )
    return [_row_to_candidate(row) for row in result.mappings().all()]


async def describe_venue_for_point(
    session: AsyncSession,
    venue_id: UUID,
    latitude: float,
    longitude: float,
) -> VenueCandidate | None:
    """Evaluate one known venue against a point (used for exit checks)."""
    result = await session.execute(
        text(_VENUE_BY_ID_SQL),
        {"venue_id": str(venue_id), "latitude": latitude, "longitude": longitude},
    )
    row = result.mappings().one_or_none()
    return None if row is None else _row_to_candidate(row)


async def get_venue_name(session: AsyncSession, venue_id: UUID) -> str | None:
    result = await session.execute(
        text("SELECT name FROM app.venues WHERE id = CAST(:venue_id AS uuid)"),
        {"venue_id": str(venue_id)},
    )
    row = result.mappings().one_or_none()
    return None if row is None else str(row["name"])


async def get_venue_timezone(session: AsyncSession, venue_id: UUID) -> str | None:
    result = await session.execute(
        text("SELECT timezone FROM app.venues WHERE id = CAST(:venue_id AS uuid)"),
        {"venue_id": str(venue_id)},
    )
    row = result.mappings().one_or_none()
    return None if row is None else str(row["timezone"])
