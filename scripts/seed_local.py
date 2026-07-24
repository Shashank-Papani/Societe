#!/usr/bin/env python3
"""Seed synthetic Los Angeles venues and users. Idempotent by slug / auth_subject."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "services" / "api"
sys.path.insert(0, str(API))

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("AUTH_PROVIDER", "local")

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import User, UserPrivacySettings, Venue, VenueHours
from app.db.session import get_redis, get_session_factory
from app.modules.venues.cache import VenueStaticCache

# Rough LA-area synthetic polygons — fictional only, not real property boundaries.
VENUES = [
    {
        "slug": "societe-neon-house",
        "name": "Société Neon House",
        "category": "nightclub",
        "description": "Synthetic club for local development.",
        "street_address": "100 Fictional Sunset Lane",
        "music_tags": ["house", "techno"],
        "experience_tags": ["dance"],
        "price_band": 3,
        "minimum_age": 21,
        "centroid": (-118.3440, 34.0955),
        "polygon": [
            (-118.3445, 34.0952),
            (-118.3435, 34.0952),
            (-118.3435, 34.0958),
            (-118.3445, 34.0958),
            (-118.3445, 34.0952),
        ],
        "supports_qr_proof": False,
        "adjacent": False,
    },
    {
        "slug": "midnight-terrace",
        "name": "Midnight Terrace",
        "category": "rooftop",
        "description": "Adjacent synthetic venue for ambiguity tests.",
        "street_address": "110 Fictional Sunset Lane",
        "music_tags": ["open_format"],
        "experience_tags": ["social", "rooftop_view"],
        "price_band": 4,
        "minimum_age": 21,
        "centroid": (-118.3438, 34.0956),
        "polygon": [
            (-118.3442, 34.0954),
            (-118.3432, 34.0954),
            (-118.3432, 34.0960),
            (-118.3442, 34.0960),
            (-118.3442, 34.0954),
        ],
        "supports_qr_proof": False,
    },
    {
        "slug": "echo-basement",
        "name": "Echo Basement",
        "category": "warehouse",
        "description": "Small synthetic basement venue.",
        "street_address": "12 Imaginary Alley",
        "music_tags": ["techno"],
        "experience_tags": ["dance", "live_set"],
        "price_band": 2,
        "minimum_age": 21,
        "centroid": (-118.2505, 34.0408),
        "polygon": [
            (-118.2507, 34.0407),
            (-118.2503, 34.0407),
            (-118.2503, 34.0409),
            (-118.2507, 34.0409),
            (-118.2507, 34.0407),
        ],
        "supports_qr_proof": False,
        "max_gps_accuracy_m": 80,
    },
    {
        "slug": "velvet-signal",
        "name": "Velvet Signal",
        "category": "lounge",
        "description": "Synthetic lounge.",
        "street_address": "500 Make-Believe Blvd",
        "music_tags": ["rnb", "hiphop"],
        "experience_tags": ["relaxing", "social"],
        "price_band": 3,
        "minimum_age": 21,
        "centroid": (-118.3850, 34.0900),
        "polygon": [
            (-118.3854, 34.0898),
            (-118.3846, 34.0898),
            (-118.3846, 34.0902),
            (-118.3854, 34.0902),
            (-118.3854, 34.0898),
        ],
        "supports_qr_proof": False,
    },
    {
        "slug": "district-static",
        "name": "District Static",
        "category": "live_music",
        "description": "Synthetic warehouse live room.",
        "street_address": "88 Synthetic Yard",
        "music_tags": ["indie", "pop"],
        "experience_tags": ["watching", "live_set"],
        "price_band": 2,
        "minimum_age": 18,
        "centroid": (-118.2700, 34.0500),
        "polygon": [
            (-118.2705, 34.0497),
            (-118.2695, 34.0497),
            (-118.2695, 34.0503),
            (-118.2705, 34.0503),
            (-118.2705, 34.0497),
        ],
        "supports_qr_proof": False,
    },
    {
        "slug": "lunar-door",
        "name": "Lunar Door",
        "category": "bar",
        "description": "Synthetic QR-capable venue (flag internal-only).",
        "street_address": "7 Crescent Fiction Way",
        "music_tags": ["house"],
        "experience_tags": ["dance"],
        "price_band": 2,
        "minimum_age": 21,
        "centroid": (-118.3000, 34.0700),
        "polygon": [
            (-118.3003, 34.0698),
            (-118.2997, 34.0698),
            (-118.2997, 34.0702),
            (-118.3003, 34.0702),
            (-118.3003, 34.0698),
        ],
        "supports_qr_proof": True,
    },
    {
        "slug": "copper-mirage",
        "name": "Copper Mirage",
        "category": "bar",
        "description": "Synthetic neighborhood bar.",
        "street_address": "42 Phantom Court",
        "music_tags": ["open_format"],
        "experience_tags": ["social"],
        "price_band": 1,
        "minimum_age": 21,
        "centroid": (-118.3200, 34.0800),
        "polygon": [
            (-118.3203, 34.0798),
            (-118.3197, 34.0798),
            (-118.3197, 34.0802),
            (-118.3203, 34.0802),
            (-118.3203, 34.0798),
        ],
        "supports_qr_proof": False,
    },
    {
        "slug": "static-garden",
        "name": "Static Garden",
        "category": "lounge",
        "description": "Synthetic outdoor-feel lounge.",
        "street_address": "15 Bloom Fiction Road",
        "music_tags": ["latin", "pop"],
        "experience_tags": ["relaxing"],
        "price_band": 3,
        "minimum_age": 21,
        "centroid": (-118.3600, 34.1000),
        "polygon": [
            (-118.3604, 34.0998),
            (-118.3596, 34.0998),
            (-118.3596, 34.1002),
            (-118.3604, 34.1002),
            (-118.3604, 34.0998),
        ],
        "supports_qr_proof": False,
    },
    {
        # Large L-shaped campus. The east tip of the south arm is inside the
        # polygon but ~385 m from the centroid, so a centroid-only candidate
        # prefilter at 150 m would wrongly drop it. Presence candidate
        # resolution must use ST_DWithin against the boundary.
        "slug": "harbor-yards-campus",
        "name": "Harbor Yards Campus",
        "category": "warehouse",
        "description": "Synthetic large irregular venue for boundary-distance tests.",
        "street_address": "900 Invented Dockside Way",
        "music_tags": ["techno", "house"],
        "experience_tags": ["dance", "live_set"],
        "price_band": 2,
        "minimum_age": 21,
        "centroid": (-118.3985, 34.0215),
        "polygon": [
            (-118.4000, 34.0200),
            (-118.3940, 34.0200),
            (-118.3940, 34.0210),
            (-118.3980, 34.0210),
            (-118.3980, 34.0240),
            (-118.4000, 34.0240),
            (-118.4000, 34.0200),
        ],
        "supports_qr_proof": False,
        "max_gps_accuracy_m": 60,
    },
    {
        "slug": "draft-whisper",
        "name": "Draft Whisper",
        "category": "bar",
        "status": "draft",
        "description": "Draft venue excluded from map.",
        "street_address": "1 Unpublished Place",
        "music_tags": ["indie"],
        "experience_tags": ["social"],
        "price_band": 1,
        "minimum_age": 21,
        "centroid": (-118.3100, 34.0600),
        "polygon": [
            (-118.3102, 34.0599),
            (-118.3098, 34.0599),
            (-118.3098, 34.0601),
            (-118.3102, 34.0601),
            (-118.3102, 34.0599),
        ],
        "supports_qr_proof": False,
    },
]


def _wkt_multipolygon(ring: list[tuple[float, float]]) -> str:
    coords = ", ".join(f"{lng} {lat}" for lng, lat in ring)
    return f"MULTIPOLYGON((({coords})))"


async def upsert_venue(session: AsyncSession, spec: dict) -> None:
    existing = await session.execute(select(Venue).where(Venue.slug == spec["slug"]))
    venue = existing.scalar_one_or_none()
    lng, lat = spec["centroid"]
    wkt = _wkt_multipolygon(spec["polygon"])
    status = spec.get("status", "active")
    if venue is None:
        await session.execute(
            text(
                """
                INSERT INTO app.venues (
                    slug, name, description, category, status, street_address, city, region,
                    country_code, timezone, minimum_age, price_band, music_tags, experience_tags,
                    boundary, centroid, geofence_version, max_gps_accuracy_m,
                    supports_qr_proof, supports_ble_proof, supports_wifi_proof
                ) VALUES (
                    :slug, :name, :description, :category, :status, :street_address, 'Los Angeles', 'CA',
                    'US', 'America/Los_Angeles', :minimum_age, :price_band, :music_tags,
                    :experience_tags,
                    ST_GeomFromText(:boundary, 4326),
                    ST_GeogFromText(:centroid),
                    1, :max_gps_accuracy_m,
                    :supports_qr_proof, false, false
                )
                """
            ),
            {
                "slug": spec["slug"],
                "name": spec["name"],
                "description": spec["description"],
                "category": spec["category"],
                "status": status,
                "street_address": spec["street_address"],
                "minimum_age": spec["minimum_age"],
                "price_band": spec["price_band"],
                "music_tags": list(spec["music_tags"]),
                "experience_tags": list(spec["experience_tags"]),
                "boundary": wkt,
                "centroid": f"POINT({lng} {lat})",
                "max_gps_accuracy_m": spec.get("max_gps_accuracy_m", 50),
                "supports_qr_proof": spec.get("supports_qr_proof", False),
            },
        )
        await session.flush()
        existing = await session.execute(select(Venue).where(Venue.slug == spec["slug"]))
        venue = existing.scalar_one()
    assert venue is not None

    # Replace hours with Thu–Sat nightlife pattern
    await session.execute(text("DELETE FROM app.venue_hours WHERE venue_id = :id"), {"id": str(venue.id)})
    for weekday in (3, 4, 5):  # Thu, Fri, Sat (Mon=0)
        session.add(
            VenueHours(
                venue_id=venue.id,
                weekday=weekday,
                opens_local=time(21, 0),
                closes_local=time(2, 0),
                closes_next_day=True,
            )
        )


async def upsert_user(session: AsyncSession, subject: str, handle: str, display: str) -> None:
    existing = await session.execute(select(User).where(User.auth_subject == subject))
    user = existing.scalar_one_or_none()
    if user is None:
        user = User(
            auth_subject=subject,
            handle=handle,
            display_name=display,
            account_status="active",
        )
        session.add(user)
        await session.flush()
        session.add(UserPrivacySettings(user_id=user.id))


async def main() -> None:
    get_settings.cache_clear()
    settings = get_settings()
    factory = get_session_factory(settings)
    async with factory() as session:
        for spec in VENUES:
            await upsert_venue(session, spec)
        await upsert_user(session, "seed-user-alpha", "seed_alpha", "Seed Alpha")
        await upsert_user(session, "seed-user-beta", "seed_beta", "Seed Beta")
        # Also ensure local-dev user exists
        await upsert_user(session, settings.local_dev_subject, "localdev", "Local Dev")
        await session.commit()

    cache = VenueStaticCache(get_redis(settings), ttl_seconds=settings.venue_static_cache_ttl_seconds)
    await cache.invalidate_all_static()
    print(f"Seeded {len(VENUES)} venues and synthetic users.")


if __name__ == "__main__":
    asyncio.run(main())
