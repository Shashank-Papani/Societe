"""Helpers for the media integration tests.

These tests talk to the real PostgreSQL, Valkey, and MinIO from the Compose
stack, because the parts most likely to break — a presigned URL a device can
actually reach, `FOR UPDATE SKIP LOCKED` claiming, cascade behaviour — are
exactly the parts a mock would paper over. When the stack is not running the
tests skip instead of failing.

Each test builds its own venue, users, and device and removes them afterwards,
so seeded local data survives a test run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import CheckIn, User, UserDevice
from app.modules.presence.leases import LeaseWrite, PresenceLeaseStore

#: A small synthetic square in Downtown Los Angeles. Not a real venue.
BOUNDARY_WKT = (
    "MULTIPOLYGON((("
    "-118.2500 34.0500, -118.2490 34.0500, -118.2490 34.0510, "
    "-118.2500 34.0510, -118.2500 34.0500)))"
)
CENTROID_WKT = "POINT(-118.2495 34.0505)"

INSERT_VENUE_SQL = """
INSERT INTO app.venues (
    id, slug, name, category, status, city, country_code, timezone,
    boundary, centroid, geofence_version
)
VALUES (
    CAST(:id AS uuid), :slug, :name, 'bar', 'active', 'Los Angeles', 'US', :timezone,
    ST_GeomFromText(:boundary, 4326), ST_GeographyFromText(:centroid), 1
)
"""


@dataclass
class MediaWorld:
    """A self-contained venue with an author, a viewer, and one device."""

    session: AsyncSession
    redis: Redis[str]
    settings: Settings
    venue_id: UUID
    timezone: str
    author: User
    viewer: User
    device: UserDevice
    check_in_id: UUID
    # Kept as plain values: cleanup rolls the session back, which expires the ORM
    # instances, and reading `author.id` afterwards would trigger a refresh.
    author_id: UUID
    viewer_id: UUID
    device_id: UUID

    async def grant_lease(
        self,
        *,
        state: str = "verified",
        venue_id: UUID | None = None,
        ghost_mode: bool = False,
        discoverable: bool = True,
        verified_for: timedelta = timedelta(minutes=2),
        now: datetime | None = None,
    ) -> None:
        moment = now or datetime.now(UTC)
        await PresenceLeaseStore(self.redis).update(
            LeaseWrite(
                user_id=self.author_id,
                venue_id=venue_id or self.venue_id,
                check_in_id=self.check_in_id,
                state=state,
                confidence=92,
                verification_level="standard",
                ghost_mode=ghost_mode,
                discoverable=discoverable,
                verified_until=moment + verified_for,
                grace_until=moment + verified_for + timedelta(minutes=5),
                lease_version=1,
            )
        )

    async def clear_lease(self) -> None:
        """The author walks out."""
        await PresenceLeaseStore(self.redis).clear(self.author_id, venue_id=self.venue_id)

    async def cleanup(self) -> None:
        """Remove only what this test created.

        Order matters: `media_assets.author_check_in_id` is ON DELETE RESTRICT,
        so assets go before the check-in they point at.
        """
        await self.session.rollback()
        venue = {"venue": str(self.venue_id)}
        await self.session.execute(
            text(
                """
                DELETE FROM app.outbox_events
                WHERE aggregate_id IN (
                    SELECT id FROM app.live_vibes WHERE venue_id = CAST(:venue AS uuid)
                    UNION ALL
                    SELECT id FROM app.media_assets WHERE venue_id = CAST(:venue AS uuid)
                    UNION ALL
                    SELECT id FROM app.check_ins WHERE venue_id = CAST(:venue AS uuid)
                )
                """
            ),
            venue,
        )
        for statement in (
            "DELETE FROM app.media_assets WHERE venue_id = CAST(:venue AS uuid)",
            "DELETE FROM app.check_ins WHERE venue_id = CAST(:venue AS uuid)",
            "DELETE FROM app.venues WHERE id = CAST(:venue AS uuid)",
        ):
            await self.session.execute(text(statement), venue)
        await self.session.execute(
            text("DELETE FROM app.users WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": [str(self.author_id), str(self.viewer_id)]},
        )
        await self.session.commit()
        await self.clear_lease()


async def build_world(
    session: AsyncSession,
    redis: Redis[str],
    settings: Settings,
    *,
    timezone: str = "America/Los_Angeles",
) -> MediaWorld:
    venue_id = uuid4()
    suffix = uuid4().hex[:10]
    await session.execute(
        text(INSERT_VENUE_SQL),
        {
            "id": str(venue_id),
            "slug": f"test-venue-{suffix}",
            "name": f"Test Venue {suffix}",
            "timezone": timezone,
            "boundary": BOUNDARY_WKT,
            "centroid": CENTROID_WKT,
        },
    )

    author = User(
        auth_subject=f"test-author-{suffix}",
        handle=f"author_{suffix}",
        display_name="Test Author",
        account_status="active",
    )
    viewer = User(
        auth_subject=f"test-viewer-{suffix}",
        handle=f"viewer_{suffix}",
        display_name="Test Viewer",
        account_status="active",
    )
    session.add_all([author, viewer])
    await session.flush()

    device = UserDevice(user_id=author.id, platform="ios", installation_id=uuid4())
    session.add(device)
    await session.flush()

    entered_at = datetime.now(UTC) - timedelta(minutes=10)
    check_in = CheckIn(
        user_id=author.id,
        venue_id=venue_id,
        state="verified",
        verification_level="standard",
        confidence_score=92,
        entry_method="fused_location",
        ghost_mode_snapshot=False,
        discoverable_snapshot=True,
        entered_at=entered_at,
        verified_at=entered_at,
        last_verified_at=entered_at,
        verified_until=datetime.now(UTC) + timedelta(minutes=2),
        grace_until=datetime.now(UTC) + timedelta(minutes=7),
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=7),
        geofence_version=1,
    )
    session.add(check_in)
    await session.commit()

    return MediaWorld(
        session=session,
        redis=redis,
        settings=settings,
        venue_id=venue_id,
        timezone=timezone,
        author=author,
        viewer=viewer,
        device=device,
        check_in_id=check_in.id,
        author_id=author.id,
        viewer_id=viewer.id,
        device_id=device.id,
    )


async def put_bytes(url: str, headers: dict[str, str], payload: bytes) -> httpx.Response:
    """Upload exactly as a device would: a single PUT to the presigned URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await client.put(url, content=payload, headers=headers)


async def object_exists(storage: object, bucket: str, key: str) -> bool:
    stat = await storage.stat_object(bucket=bucket, key=key)  # type: ignore[attr-defined]
    return stat is not None
