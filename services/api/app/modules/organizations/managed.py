"""Managed venue profile updates for organization staff."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import User, Venue
from app.modules.organizations.authz import OrganizationAuthorizer, OrgPermission
from app.modules.organizations.schemas import ManagedVenueProfileUpdate
from app.modules.organizations.service import require_venue_organizations_enabled


class ManagedVenueService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis[str],
        settings: Settings,
    ) -> None:
        self._session = session
        self._settings = settings
        self._authz = OrganizationAuthorizer(session)
        _ = redis

    async def update_managed_profile(
        self,
        user: User,
        venue_id: UUID,
        body: ManagedVenueProfileUpdate,
        now: datetime,
    ) -> dict[str, Any]:
        require_venue_organizations_enabled(self._settings)
        await self._authz.require_venue_permission(
            user, venue_id, OrgPermission.VENUE_PROFILE_UPDATE
        )

        result = await self._session.execute(
            select(Venue).where(Venue.id == venue_id).with_for_update().limit(1)
        )
        venue = result.scalar_one_or_none()
        if venue is None:
            raise AppError("VENUE_NOT_FOUND", "Venue not found.", status_code=404)

        if body.description is not None:
            venue.description = body.description
        if body.music_tags is not None:
            venue.music_tags = list(body.music_tags)
        if body.experience_tags is not None:
            venue.experience_tags = list(body.experience_tags)
        venue.updated_at = now
        await self._session.flush()
        await self._session.commit()

        return {
            "venue_id": str(venue.id),
            "description": venue.description,
            "music_tags": list(venue.music_tags or []),
            "experience_tags": list(venue.experience_tags or []),
        }
