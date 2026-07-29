"""Helpers for Phase 7A organization ownership tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuthIdentity,
    MediaAsset,
    MediaDerivative,
    Organization,
    OrganizationMember,
    Venue,
)


def auth_headers(client: TestClient, *, persona: str = "alpha") -> dict[str, str]:
    token = client.post("/v1/auth/local/token", json={"persona": persona}).json()["data"][
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


def me(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    return client.get("/v1/me", headers=headers).json()["data"]


async def attach_email(session: AsyncSession, *, user_id: UUID, email: str) -> AuthIdentity:
    identity = AuthIdentity(
        user_id=user_id,
        provider="email",
        normalized_email=email.strip().lower(),
        verified_at=datetime.now(UTC),
    )
    session.add(identity)
    await session.commit()
    return identity


async def first_active_venue(session: AsyncSession) -> Venue:
    result = await session.execute(
        select(Venue).where(Venue.status == "active").order_by(Venue.name).limit(1)
    )
    venue = result.scalar_one_or_none()
    if venue is None:
        raise RuntimeError("No active venue seeded; run `make seed`")
    return venue


async def claimable_venue(session: AsyncSession) -> Venue:
    """Return an active venue with no active managing organization link.

    If every seeded venue is already linked (leftover from earlier tests),
    unlink one so claim/cover flows can run.
    """
    from app.db.models import VenueOrganization

    linked_ids = select(VenueOrganization.venue_id).where(VenueOrganization.status == "active")
    result = await session.execute(
        select(Venue)
        .where(Venue.status == "active", Venue.id.not_in(linked_ids))
        .order_by(Venue.name)
        .limit(1)
    )
    venue = result.scalar_one_or_none()
    if venue is not None:
        return venue

    link_result = await session.execute(
        select(VenueOrganization)
        .where(VenueOrganization.status == "active")
        .order_by(VenueOrganization.linked_at.asc())
        .limit(1)
    )
    link = link_result.scalar_one_or_none()
    if link is None:
        return await first_active_venue(session)

    link.status = "unlinked"
    link.unlinked_at = datetime.now(UTC)
    owned = await session.get(Venue, link.venue_id)
    if owned is not None:
        owned.primary_cover_media_id = None
    await session.commit()
    assert owned is not None
    return owned


async def unlink_venue(session: AsyncSession, venue_id: UUID) -> None:
    from app.db.models import VenueOrganization

    result = await session.execute(
        select(VenueOrganization).where(
            VenueOrganization.venue_id == venue_id,
            VenueOrganization.status == "active",
        )
    )
    for link in result.scalars().all():
        link.status = "unlinked"
        link.unlinked_at = datetime.now(UTC)
    venue = await session.get(Venue, venue_id)
    if venue is not None:
        venue.primary_cover_media_id = None
    await session.commit()


async def insert_venue_owned_media(
    session: AsyncSession,
    *,
    venue_id: UUID,
    organization_id: UUID,
    owner_user_id: UUID,
    lifecycle_status: str = "ready",
    moderation_status: str = "approved",
    with_derivative: bool = True,
) -> MediaAsset:
    asset = MediaAsset(
        owner_user_id=owner_user_id,
        venue_id=venue_id,
        purpose="venue_owned",
        organization_id=organization_id,
        author_check_in_id=None,
        device_id=None,
        media_type="image",
        lifecycle_status=lifecycle_status,
        moderation_status=moderation_status,
        attribution_mode="attributed",
        quarantine_object_key=f"venue-owned/{organization_id}/{uuid4()}.jpg",
        declared_mime_type="image/jpeg",
        declared_byte_size=12_345,
        intent_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    session.add(asset)
    await session.flush()
    if with_derivative and lifecycle_status == "ready":
        session.add(
            MediaDerivative(
                media_asset_id=asset.id,
                variant_type="feed_poster",
                generation=1,
                status="ready",
                object_key=f"processed/venue-cover/{asset.id}/feed_poster.jpg",
                mime_type="image/jpeg",
                byte_size=12_345,
                checksum_sha256="0" * 64,
                width=1080,
                height=1350,
            )
        )
    await session.commit()
    await session.refresh(asset)
    return asset


async def load_membership(
    session: AsyncSession, *, organization_id: UUID, user_id: UUID
) -> OrganizationMember | None:
    result = await session.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "active",
        )
    )
    return result.scalar_one_or_none()


async def load_organization(session: AsyncSession, organization_id: UUID) -> Organization | None:
    return await session.get(Organization, organization_id)
