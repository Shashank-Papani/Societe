"""User / official Story upload intent shape (no LiveVibe, correct purpose)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from media_support import build_world
from organization_support import auth_headers, claimable_venue, me
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models import LiveVibe, MediaAsset, Story, User
from app.modules.stories.schemas import (
    CreateOfficialStoryUploadRequest,
    CreateUserStoryUploadRequest,
)
from app.modules.stories.service import StoryService


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


@pytest.mark.asyncio
async def test_user_story_upload_creates_no_live_vibe(
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    world = await build_world(db_session, valkey, media_settings)
    try:
        await world.grant_lease()
        service = StoryService(db_session, valkey, media_settings)
        created = await service.create_user_story_upload(
            user=world.author,
            request=CreateUserStoryUploadRequest(
                venue_id=world.venue_id,
                device_id=world.device_id,
                media_type="image",
                mime_type="image/jpeg",
                byte_size=4096,
                caption="vibe check",
                attribution_mode="anonymous",
            ),
            now=datetime.now(UTC),
        )
        asset = await db_session.get(MediaAsset, created.media_asset_id)
        assert asset is not None
        assert asset.purpose == "user_story"
        assert asset.organization_id is None
        assert asset.author_check_in_id is not None
        assert asset.device_id == world.device_id

        story = await db_session.get(Story, created.story_id)
        assert story is not None
        assert story.author_type == "user"
        assert story.attribution_mode == "anonymous"

        vibe_count = await db_session.execute(
            select(func.count()).select_from(LiveVibe).where(LiveVibe.media_asset_id == asset.id)
        )
        assert int(vibe_count.scalar_one()) == 0
    finally:
        await world.cleanup()


@pytest.mark.asyncio
async def test_official_story_upload_is_venue_owned(
    client: TestClient,
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    headers = auth_headers(client, persona="alpha")
    venue = await claimable_venue(db_session)
    org = client.post(
        "/v1/organizations",
        headers=_idem(headers),
        json={"name": f"Upload Org {uuid4().hex[:8]}"},
    )
    assert org.status_code == 201, org.text
    claim = client.post(
        f"/v1/venues/{venue.id}/claims",
        headers=_idem(headers),
        json={"organization_id": org.json()["data"]["id"]},
    )
    assert claim.status_code == 201, claim.text
    approved = client.post(
        f"/v1/admin/venue-claims/{claim.json()['data']['id']}/approve",
        headers=headers,
    )
    assert approved.status_code == 200, approved.text

    owner = await db_session.get(User, UUID(me(client, headers)["id"]))
    assert owner is not None
    service = StoryService(db_session, valkey, media_settings)
    created = await service.create_official_story_upload(
        user=owner,
        venue_id=venue.id,
        request=CreateOfficialStoryUploadRequest(
            media_type="image",
            mime_type="image/jpeg",
            byte_size=2048,
        ),
        now=datetime.now(UTC),
    )
    asset = await db_session.get(MediaAsset, created.media_asset_id)
    assert asset is not None
    assert asset.purpose == "venue_owned"
    assert asset.organization_id is not None
    assert asset.author_check_in_id is None
    assert asset.device_id is None

    story = await db_session.get(Story, created.story_id)
    assert story is not None
    assert story.author_type == "venue"
    assert story.author_user_id is None
    assert story.attribution_mode == "official"


@pytest.mark.asyncio
async def test_official_story_upload_http_idempotency(
    client: TestClient,
    db_session: AsyncSession,
) -> None:
    headers = auth_headers(client, persona="alpha")
    venue = await claimable_venue(db_session)
    org = client.post(
        "/v1/organizations",
        headers=_idem(headers),
        json={"name": f"Idem Org {uuid4().hex[:8]}"},
    )
    assert org.status_code == 201, org.text
    claim = client.post(
        f"/v1/venues/{venue.id}/claims",
        headers=_idem(headers),
        json={"organization_id": org.json()["data"]["id"]},
    )
    assert claim.status_code == 201, claim.text
    approved = client.post(
        f"/v1/admin/venue-claims/{claim.json()['data']['id']}/approve",
        headers=headers,
    )
    assert approved.status_code == 200, approved.text

    key = str(uuid4())
    body = {"media_type": "image", "mime_type": "image/jpeg", "byte_size": 2048}
    first = client.post(
        f"/v1/venues/{venue.id}/official-stories/uploads",
        headers={**headers, "Idempotency-Key": key},
        json=body,
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/v1/venues/{venue.id}/official-stories/uploads",
        headers={**headers, "Idempotency-Key": key},
        json=body,
    )
    assert second.status_code == 201, second.text
    assert first.json()["data"]["story_id"] == second.json()["data"]["story_id"]
    assert first.json()["data"]["media_asset_id"] == second.json()["data"]["media_asset_id"]
    assert first.json()["data"]["attribution_mode"] == "official"
    assert "object_key" not in first.json()["data"]
    assert "quarantine_object_key" not in first.json()["data"]
    # Signed PUT URL is intentional for the uploader; public projections omit it.
    assert "upload" in first.json()["data"]
    assert "url" in first.json()["data"]["upload"]
