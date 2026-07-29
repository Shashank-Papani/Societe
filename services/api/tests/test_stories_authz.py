"""Authorization matrices for user and official Stories."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from media_support import build_world
from organization_support import auth_headers, claimable_venue, me
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import OrganizationMember, User
from app.modules.stories.schemas import (
    CreateOfficialStoryUploadRequest,
    CreateUserStoryUploadRequest,
)
from app.modules.stories.service import StoryService


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


async def _link_venue(
    client: TestClient,
    db_session: AsyncSession,
    headers: dict[str, str],
) -> tuple[UUID, str]:
    venue = await claimable_venue(db_session)
    org = client.post(
        "/v1/organizations",
        headers=_idem(headers),
        json={"name": f"Story Authz Org {uuid4().hex[:8]}"},
    )
    assert org.status_code == 201, org.text
    org_id = org.json()["data"]["id"]
    claim = client.post(
        f"/v1/venues/{venue.id}/claims",
        headers=_idem(headers),
        json={"organization_id": org_id},
    )
    assert claim.status_code == 201, claim.text
    approved = client.post(
        f"/v1/admin/venue-claims/{claim.json()['data']['id']}/approve",
        headers=headers,
    )
    assert approved.status_code == 200, approved.text
    return venue.id, org_id


@pytest.mark.asyncio
async def test_user_story_requires_presence(
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    world = await build_world(db_session, valkey, media_settings)
    try:
        service = StoryService(db_session, valkey, media_settings)
        request = CreateUserStoryUploadRequest(
            venue_id=world.venue_id,
            device_id=world.device_id,
            media_type="image",
            mime_type="image/jpeg",
            byte_size=1024,
            attribution_mode="attributed",
        )
        with pytest.raises(AppError) as exc:
            await service.create_user_story_upload(
                user=world.author, request=request, now=datetime.now(UTC)
            )
        assert exc.value.code == "STORY_POSTING_NOT_AUTHORIZED"

        await world.grant_lease()
        created = await service.create_user_story_upload(
            user=world.author, request=request, now=datetime.now(UTC)
        )
        assert created.publication_status == "draft"
        assert created.attribution_mode == "attributed"
    finally:
        await world.cleanup()


@pytest.mark.asyncio
async def test_user_story_disabled_by_feature_flag(
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(media_settings, "ff_stories", False)
    world = await build_world(db_session, valkey, media_settings)
    try:
        await world.grant_lease()
        service = StoryService(db_session, valkey, media_settings)
        with pytest.raises(AppError) as exc:
            await service.create_user_story_upload(
                user=world.author,
                request=CreateUserStoryUploadRequest(
                    venue_id=world.venue_id,
                    device_id=world.device_id,
                    media_type="image",
                    mime_type="image/jpeg",
                    byte_size=1024,
                    attribution_mode="attributed",
                ),
                now=datetime.now(UTC),
            )
        assert exc.value.code == "STORIES_DISABLED"
    finally:
        await world.cleanup()


@pytest.mark.asyncio
async def test_official_story_role_matrix(
    client: TestClient,
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    headers = auth_headers(client, persona="alpha")
    venue_id, org_id = await _link_venue(client, db_session, headers)
    owner_id = UUID(me(client, headers)["id"])
    owner = await db_session.get(User, owner_id)
    assert owner is not None

    service = StoryService(db_session, valkey, media_settings)
    request = CreateOfficialStoryUploadRequest(
        media_type="image",
        mime_type="image/jpeg",
        byte_size=2048,
    )
    # Official upload does not require physical presence.
    created = await service.create_official_story_upload(
        user=owner, venue_id=venue_id, request=request, now=datetime.now(UTC)
    )
    assert created.attribution_mode == "official"
    assert created.upload is not None

    beta_headers = auth_headers(client, persona="beta")
    analyst_id = UUID(me(client, beta_headers)["id"])
    analyst = await db_session.get(User, analyst_id)
    assert analyst is not None
    db_session.add(
        OrganizationMember(
            organization_id=UUID(org_id),
            user_id=analyst.id,
            role="analyst",
            status="active",
        )
    )
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await service.create_official_story_upload(
            user=analyst, venue_id=venue_id, request=request, now=datetime.now(UTC)
        )
    assert exc.value.code == "ORGANIZATION_FORBIDDEN"


@pytest.mark.asyncio
async def test_official_story_denies_removed_suspended_unlinked_cross_org(
    client: TestClient,
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    from organization_support import attach_email, unlink_venue

    headers = auth_headers(client, persona="alpha")
    venue_id, org_id = await _link_venue(client, db_session, headers)
    request = CreateOfficialStoryUploadRequest(
        media_type="image",
        mime_type="image/jpeg",
        byte_size=2048,
    )
    service = StoryService(db_session, valkey, media_settings)

    # Cross-org: beta owns a different org and cannot publish to venue_id.
    beta_headers = auth_headers(client, persona="beta")
    other_org = client.post(
        "/v1/organizations",
        headers=_idem(beta_headers),
        json={"name": f"Other Org {uuid4().hex[:8]}"},
    )
    assert other_org.status_code == 201, other_org.text
    beta = await db_session.get(User, UUID(me(client, beta_headers)["id"]))
    assert beta is not None
    with pytest.raises(AppError) as cross:
        await service.create_official_story_upload(
            user=beta, venue_id=venue_id, request=request, now=datetime.now(UTC)
        )
    assert cross.value.code in {"ORGANIZATION_FORBIDDEN", "VENUE_NOT_MANAGED"}

    # Invite a fresh email identity as manager on org, accept, then remove.
    email = f"removed-{uuid4().hex[:8]}@example.test"
    await attach_email(db_session, user_id=beta.id, email=email)
    invited = client.post(
        f"/v1/organizations/{org_id}/invitations",
        headers=_idem(headers),
        json={"email": email, "role": "manager"},
    )
    assert invited.status_code == 201, invited.text
    accepted = client.post(
        f"/v1/organization-invitations/{invited.json()['data']['token']}/accept",
        headers=beta_headers,
    )
    assert accepted.status_code == 200, accepted.text
    removed = client.delete(
        f"/v1/organizations/{org_id}/members/{beta.id}",
        headers=headers,
    )
    assert removed.status_code == 200, removed.text
    await db_session.refresh(beta)
    with pytest.raises(AppError) as rem:
        await service.create_official_story_upload(
            user=beta, venue_id=venue_id, request=request, now=datetime.now(UTC)
        )
    assert rem.value.code == "ORGANIZATION_FORBIDDEN"

    # Suspended org blocks owner.
    from app.db.models import Organization

    org = await db_session.get(Organization, UUID(org_id))
    assert org is not None
    org.status = "suspended"
    await db_session.commit()
    owner = await db_session.get(User, UUID(me(client, headers)["id"]))
    assert owner is not None
    with pytest.raises(AppError) as sus:
        await service.create_official_story_upload(
            user=owner, venue_id=venue_id, request=request, now=datetime.now(UTC)
        )
    assert sus.value.code in {"ORGANIZATION_INACTIVE", "ORGANIZATION_FORBIDDEN"}

    org.status = "active"
    await db_session.commit()
    await unlink_venue(db_session, venue_id)
    with pytest.raises(AppError) as unlinked:
        await service.create_official_story_upload(
            user=owner, venue_id=venue_id, request=request, now=datetime.now(UTC)
        )
    assert unlinked.value.code in {"VENUE_NOT_MANAGED", "ORGANIZATION_FORBIDDEN"}
