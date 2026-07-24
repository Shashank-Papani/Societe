from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Venue, VenueHours
from app.modules.venues.filters import MapVenuesQuery


@dataclass(frozen=True)
class NearbyVenueRow:
    id: UUID
    slug: str
    name: str
    category: str
    price_band: int | None
    music_tags: list[str]
    experience_tags: list[str]
    minimum_age: int | None
    city: str
    region: str | None
    distance_m: float
    centroid_lng: float
    centroid_lat: float


class VenueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, venue_id: UUID) -> Venue | None:
        result = await self._session.execute(select(Venue).where(Venue.id == venue_id))
        return result.scalar_one_or_none()

    async def list_hours(self, venue_id: UUID) -> list[VenueHours]:
        result = await self._session.execute(
            select(VenueHours)
            .where(VenueHours.venue_id == venue_id)
            .order_by(VenueHours.weekday, VenueHours.opens_local)
        )
        return list(result.scalars().all())

    async def nearby(
        self, query: MapVenuesQuery, *, cursor_distance: float | None, cursor_id: UUID | None
    ) -> list[NearbyVenueRow]:
        params: dict[str, Any] = {
            "longitude": query.longitude,
            "latitude": query.latitude,
            "radius_m": query.radius_m,
            "limit": query.limit + 1,
        }
        filters_sql = ["v.status = 'active'", "ST_DWithin(v.centroid, up.geog, :radius_m)"]
        if query.categories:
            params["categories"] = list(query.categories)
            filters_sql.append("v.category = ANY(:categories)")
        if query.price_bands:
            params["price_bands"] = query.price_bands
            filters_sql.append("v.price_band = ANY(:price_bands)")
        if query.music_tags:
            params["music_tags"] = list(query.music_tags)
            filters_sql.append("v.music_tags && CAST(:music_tags AS text[])")
        if query.experience_tags:
            params["experience_tags"] = list(query.experience_tags)
            filters_sql.append("v.experience_tags && CAST(:experience_tags AS text[])")
        if query.minimum_age is not None:
            params["minimum_age"] = query.minimum_age
            filters_sql.append("(v.minimum_age IS NULL OR v.minimum_age <= :minimum_age)")

        cursor_sql = ""
        if cursor_distance is not None and cursor_id is not None:
            params["cursor_distance"] = cursor_distance
            params["cursor_id"] = str(cursor_id)
            cursor_sql = """
            AND (
                distance_m > :cursor_distance
                OR (distance_m = :cursor_distance AND v.id > CAST(:cursor_id AS uuid))
            )
            """

        where_clause = " AND ".join(filters_sql)
        sql = f"""
        WITH user_point AS (
            SELECT ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography AS geog
        ),
        ranked AS (
            SELECT
                v.id,
                v.slug,
                v.name,
                v.category,
                v.price_band,
                v.music_tags,
                v.experience_tags,
                v.minimum_age,
                v.city,
                v.region,
                ST_Distance(v.centroid, up.geog) AS distance_m,
                ST_X(v.centroid::geometry) AS centroid_lng,
                ST_Y(v.centroid::geometry) AS centroid_lat
            FROM app.venues v
            CROSS JOIN user_point up
            WHERE {where_clause}
        )
        SELECT *
        FROM ranked v
        WHERE TRUE
        {cursor_sql}
        ORDER BY distance_m ASC, id ASC
        LIMIT :limit
        """
        result = await self._session.execute(text(sql), params)
        rows = []
        for row in result.mappings().all():
            rows.append(
                NearbyVenueRow(
                    id=row["id"],
                    slug=row["slug"],
                    name=row["name"],
                    category=row["category"],
                    price_band=row["price_band"],
                    music_tags=list(row["music_tags"] or []),
                    experience_tags=list(row["experience_tags"] or []),
                    minimum_age=row["minimum_age"],
                    city=row["city"],
                    region=row["region"],
                    distance_m=float(row["distance_m"]),
                    centroid_lng=float(row["centroid_lng"]),
                    centroid_lat=float(row["centroid_lat"]),
                )
            )
        return rows
