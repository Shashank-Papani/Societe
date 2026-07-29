from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import MediaAsset, MediaDerivative, Venue
from app.db.session import get_redis
from app.modules.media.storage import build_object_storage
from app.modules.venues.cache import VenueStaticCache
from app.modules.venues.filters import MapVenuesQuery
from app.modules.venues.repository import VenueRepository
from app.shared.cursors import query_fingerprint, sign_cursor, verify_cursor

logger = get_logger(__name__)

# Prefer poster-like ready derivatives; never expose object keys to clients.
_COVER_VARIANT_PREFERENCE = (
    "feed_poster",
    "image_1080",
    "video_poster",
    "image_720",
    "thumbnail",
)


class VenueService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._repo = VenueRepository(session)
        self._cache = VenueStaticCache(
            get_redis(settings),
            ttl_seconds=settings.venue_static_cache_ttl_seconds,
        )

    async def map_venues(self, query: MapVenuesQuery) -> dict[str, Any]:
        if query.age_bands is not None:
            raise AppError(
                "FILTER_NOT_AVAILABLE",
                "age_bands depends on live venue analytics and is not available yet.",
                status_code=400,
            )
        if query.crowd_buckets is not None:
            raise AppError(
                "FILTER_NOT_AVAILABLE",
                "crowd_buckets depends on live venue analytics and is not available yet.",
                status_code=400,
            )

        qfp = query_fingerprint(
            latitude=query.latitude,
            longitude=query.longitude,
            radius_m=query.radius_m,
            filters=query.filters_for_fingerprint(),
        )
        cursor_distance: float | None = None
        cursor_id: UUID | None = None
        if query.cursor:
            payload = verify_cursor(
                cursor=query.cursor,
                expected_qfp=qfp,
                secret=self._settings.cursor_hmac_secret.get_secret_value(),
            )
            cursor_distance = float(payload["distance_m"])
            cursor_id = UUID(str(payload["venue_id"]))

        # Always authoritative PostGIS query — do not filter by H3 candidate IDs.
        rows = await self._repo.nearby(query, cursor_distance=cursor_distance, cursor_id=cursor_id)
        page = rows[: query.limit]
        has_more = len(rows) > query.limit

        cached = await self._cache.get_many([row.id for row in page])
        items: list[dict[str, Any]] = []
        to_store: dict[str, dict[str, Any]] = {}
        for row in page:
            key = str(row.id)
            if key in cached:
                card = dict(cached[key])
            else:
                card = {
                    "id": str(row.id),
                    "slug": row.slug,
                    "name": row.name,
                    "category": row.category,
                    "price_band": row.price_band,
                    "music_tags": row.music_tags,
                    "experience_tags": row.experience_tags,
                    "minimum_age": row.minimum_age,
                    "city": row.city,
                    "region": row.region,
                    "map_pin": {
                        "latitude": row.centroid_lat,
                        "longitude": row.centroid_lng,
                    },
                }
                to_store[key] = card
            card = dict(card)
            card["distance_m"] = round(row.distance_m, 1)
            items.append(card)

        if to_store:
            await self._cache.set_many(to_store)

        next_cursor = None
        if has_more and page:
            last = page[-1]
            next_cursor = sign_cursor(
                distance_m=last.distance_m,
                venue_id=str(last.id),
                qfp=qfp,
                secret=self._settings.cursor_hmac_secret.get_secret_value(),
                ttl_seconds=self._settings.cursor_ttl_seconds,
            )
        return {"items": items, "next_cursor": next_cursor}

    async def get_public_detail(self, venue_id: UUID) -> dict[str, Any]:
        venue = await self._repo.get_by_id(venue_id)
        if venue is None or venue.status == "draft":
            raise AppError("VENUE_NOT_FOUND", "Venue not found.", status_code=404)

        coords = await self._session.execute(
            text(
                """
                SELECT ST_Y(centroid::geometry) AS lat, ST_X(centroid::geometry) AS lng
                FROM app.venues WHERE id = :id
                """
            ),
            {"id": str(venue_id)},
        )
        coord = coords.mappings().one()
        hours = await self._repo.list_hours(venue_id)
        cover_media_id, cover_image_url = await self._cover_projection(venue)
        return {
            "id": str(venue.id),
            "slug": venue.slug,
            "name": venue.name,
            "description": venue.description,
            "category": venue.category,
            "status": venue.status,
            "street_address": venue.street_address,
            "city": venue.city,
            "region": venue.region,
            "country_code": venue.country_code,
            "timezone": venue.timezone,
            "minimum_age": venue.minimum_age,
            "price_band": venue.price_band,
            "music_tags": list(venue.music_tags or []),
            "experience_tags": list(venue.experience_tags or []),
            "cover_media_id": cover_media_id,
            "cover_image_url": cover_image_url,
            "centroid": {
                "latitude": float(coord["lat"]),
                "longitude": float(coord["lng"]),
            },
            "hours": [
                {
                    "weekday": h.weekday,
                    "opens_local": h.opens_local.isoformat(),
                    "closes_local": h.closes_local.isoformat(),
                    "closes_next_day": h.closes_next_day,
                }
                for h in hours
            ],
        }

    async def _cover_projection(self, venue: Venue) -> tuple[str | None, str | None]:
        """Return safe cover id + signed URL. Never expose object keys."""
        media_id = venue.primary_cover_media_id
        if media_id is None:
            return None, None

        asset = await self._session.get(MediaAsset, media_id)
        if (
            asset is None
            or asset.deleted_at is not None
            or asset.purpose != "venue_owned"
            or asset.venue_id != venue.id
            or asset.lifecycle_status != "ready"
            or asset.moderation_status != "approved"
        ):
            return None, None

        cover_media_id = str(asset.id)
        result = await self._session.execute(
            select(MediaDerivative).where(
                MediaDerivative.media_asset_id == asset.id,
                MediaDerivative.generation == asset.generation,
                MediaDerivative.status == "ready",
            )
        )
        derivatives = list(result.scalars().all())
        if not derivatives:
            return cover_media_id, None

        by_type = {d.variant_type: d for d in derivatives}
        chosen: MediaDerivative | None = None
        for variant in _COVER_VARIANT_PREFERENCE:
            if variant in by_type:
                chosen = by_type[variant]
                break
        if chosen is None:
            chosen = derivatives[0]

        try:
            storage = build_object_storage(self._settings)
            url = await storage.presign_get(
                bucket=self._settings.media_processed_bucket,
                key=chosen.object_key,
                expires_in=self._settings.media_signed_url_ttl_seconds,
            )
        except Exception:
            logger.warning(
                "venue_cover_signed_url_unavailable",
                venue_id=str(venue.id),
                media_asset_id=cover_media_id,
            )
            return cover_media_id, None

        return cover_media_id, url
