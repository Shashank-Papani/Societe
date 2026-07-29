"""Venue primary cover selection (venue-owned media only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import LiveVibe, MediaAsset, OutboxEvent, User, Venue, VenueOrganization
from app.modules.organizations.audit import (
    VENUE_COVER_REMOVED,
    VENUE_COVER_SELECTED,
    append_audit_event,
)
from app.modules.organizations.authz import (
    ACTIVE_VENUE_LINK,
    OrganizationAuthorizer,
    OrgPermission,
)
from app.modules.organizations.service import require_venue_organizations_enabled


class CoverService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis[str],
        settings: Settings,
    ) -> None:
        self._session = session
        self._settings = settings
        self._authz = OrganizationAuthorizer(session)
        _ = redis  # reserved for future cover rate limits

    def _require_enabled(self) -> None:
        require_venue_organizations_enabled(self._settings)

    def _emit(
        self,
        *,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        occurred_at: datetime,
        payload: dict[str, object],
    ) -> None:
        self._session.add(
            OutboxEvent(
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                payload=payload,
                occurred_at=occurred_at,
                available_at=occurred_at,
            )
        )

    async def set_cover(
        self,
        user: User,
        venue_id: UUID,
        media_asset_id: UUID,
        now: datetime,
    ) -> dict[str, Any]:
        self._require_enabled()
        ctx = await self._authz.require_venue_permission(
            user, venue_id, OrgPermission.VENUE_COVER_UPDATE
        )

        venue = await self._session.execute(
            select(Venue).where(Venue.id == venue_id).with_for_update().limit(1)
        )
        venue_row = venue.scalar_one_or_none()
        if venue_row is None:
            raise AppError("VENUE_NOT_FOUND", "Venue not found.", status_code=404)

        link = await self._session.execute(
            select(VenueOrganization)
            .where(
                VenueOrganization.venue_id == venue_id,
                VenueOrganization.status == ACTIVE_VENUE_LINK,
            )
            .limit(1)
        )
        venue_org = link.scalar_one_or_none()
        if venue_org is None:
            raise AppError(
                "VENUE_NOT_MANAGED",
                "This venue is not linked to a managing organization.",
                status_code=403,
            )

        media = await self._session.get(MediaAsset, media_asset_id)
        if media is None or media.deleted_at is not None:
            raise AppError("MEDIA_NOT_FOUND", "Media asset was not found.", status_code=404)

        if (
            media.purpose != "venue_owned"
            or media.organization_id != venue_org.organization_id
            or media.venue_id != venue_id
            or media.lifecycle_status != "ready"
            or media.moderation_status != "approved"
        ):
            raise AppError(
                "COVER_MEDIA_INVALID",
                "Cover media must be ready, approved, venue-owned media for this venue.",
                status_code=400,
            )

        vibe = await self._session.execute(
            select(LiveVibe).where(LiveVibe.media_asset_id == media_asset_id).limit(1)
        )
        if vibe.scalar_one_or_none() is not None:
            raise AppError(
                "COVER_MEDIA_INVALID",
                "Live Vibe media cannot be used as a venue cover.",
                status_code=400,
            )

        venue_row.primary_cover_media_id = media_asset_id
        venue_row.updated_at = now
        await self._session.flush()

        await append_audit_event(
            self._session,
            event_type=VENUE_COVER_SELECTED,
            actor_user_id=user.id,
            organization_id=ctx.organization.id,
            venue_id=venue_id,
            target_type="media_asset",
            target_id=media_asset_id,
            metadata={"media_asset_id": str(media_asset_id)},
        )
        self._emit(
            aggregate_type="venue",
            aggregate_id=venue_id,
            event_type="venue.cover.changed",
            occurred_at=now,
            payload={
                "venue_id": str(venue_id),
                "media_asset_id": str(media_asset_id),
                "organization_id": str(ctx.organization.id),
            },
        )
        await self._session.commit()
        return {
            "venue_id": str(venue_id),
            "cover_media_id": str(media_asset_id),
        }

    async def remove_cover(self, user: User, venue_id: UUID, now: datetime) -> dict[str, Any]:
        self._require_enabled()
        ctx = await self._authz.require_venue_permission(
            user, venue_id, OrgPermission.VENUE_COVER_UPDATE
        )

        venue = await self._session.execute(
            select(Venue).where(Venue.id == venue_id).with_for_update().limit(1)
        )
        venue_row = venue.scalar_one_or_none()
        if venue_row is None:
            raise AppError("VENUE_NOT_FOUND", "Venue not found.", status_code=404)

        previous = venue_row.primary_cover_media_id
        venue_row.primary_cover_media_id = None
        venue_row.updated_at = now
        await self._session.flush()

        await append_audit_event(
            self._session,
            event_type=VENUE_COVER_REMOVED,
            actor_user_id=user.id,
            organization_id=ctx.organization.id,
            venue_id=venue_id,
            target_type="venue",
            target_id=venue_id,
            metadata={
                "previous_media_asset_id": str(previous) if previous else None,
            },
        )
        self._emit(
            aggregate_type="venue",
            aggregate_id=venue_id,
            event_type="venue.cover.changed",
            occurred_at=now,
            payload={
                "venue_id": str(venue_id),
                "media_asset_id": None,
                "organization_id": str(ctx.organization.id),
            },
        )
        await self._session.commit()
        return {"venue_id": str(venue_id), "cover_media_id": None}
