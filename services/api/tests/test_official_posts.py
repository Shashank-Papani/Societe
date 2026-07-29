"""Official venue posts — persistence, HTTP idempotency, privacy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from organization_support import auth_headers, claimable_venue, me
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from story_support import insert_text_official_post

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import User
from app.modules.stories.official_posts import OfficialPostService, validate_cta_url
from app.modules.stories.schemas import CreateOfficialPostRequest


def _idem(headers: dict[str, str], key: str | None = None) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key or str(uuid4())}


async def _link(
    client: TestClient, db_session: AsyncSession, headers: dict[str, str]
) -> tuple[UUID, str]:
    venue = await claimable_venue(db_session)
    org = client.post(
        "/v1/organizations",
        headers=_idem(headers),
        json={"name": f"Posts Org {uuid4().hex[:8]}"},
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
    return venue.id, org.json()["data"]["id"]


@pytest.mark.asyncio
async def test_official_posts_text_publish_archive(
    client: TestClient,
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    headers = auth_headers(client, persona="alpha")
    venue_id, _org_id = await _link(client, db_session, headers)

    owner = await db_session.get(User, UUID(me(client, headers)["id"]))
    assert owner is not None
    service = OfficialPostService(db_session, valkey, media_settings)

    with pytest.raises(AppError) as exc:
        validate_cta_url("http://insecure.example")
    assert exc.value.code == "OFFICIAL_POST_CTA_INVALID"

    created = await service.create_post(
        user=owner,
        venue_id=venue_id,
        request=CreateOfficialPostRequest(
            post_type="announcement",
            title="Guest list",
            body="Names at the door.",
            call_to_action_type="link",
            call_to_action_url="https://example.com/guest",
        ),
        now=datetime.now(UTC),
    )
    assert created.upload is None
    assert created.post.publication_status == "published"
    assert created.post.is_official is True
    assert created.post.author_label
    assert "created_by_user_id" not in created.post.model_dump()

    listed = await service.list_public_posts(venue_id=venue_id, now=datetime.now(UTC))
    assert any(item.post_id == created.post.post_id for item in listed.items)

    got = await service.get_public_post(post_id=created.post.post_id, now=datetime.now(UTC))
    assert got.body == "Names at the door."
    assert got.is_official is True

    archived = await service.archive_post(
        user=owner, post_id=created.post.post_id, now=datetime.now(UTC)
    )
    assert archived.publication_status == "archived"

    listed_after = await service.list_public_posts(venue_id=venue_id, now=datetime.now(UTC))
    assert all(item.post_id != created.post.post_id for item in listed_after.items)


@pytest.mark.asyncio
async def test_official_posts_remain_after_24_hours(
    client: TestClient,
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> None:
    headers = auth_headers(client, persona="alpha")
    venue_id, org_id = await _link(client, db_session, headers)
    owner = await db_session.get(User, UUID(me(client, headers)["id"]))
    assert owner is not None
    past = datetime.now(UTC) - timedelta(hours=30)
    post = await insert_text_official_post(
        db_session,
        user=owner,
        venue_id=venue_id,
        organization_id=UUID(org_id),
        now=past,
    )
    service = OfficialPostService(db_session, valkey, media_settings)
    listed = await service.list_public_posts(venue_id=venue_id, now=datetime.now(UTC))
    assert any(item.post_id == post.id for item in listed.items)


@pytest.mark.asyncio
async def test_official_post_http_idempotency(
    client: TestClient,
    db_session: AsyncSession,
) -> None:
    headers = auth_headers(client, persona="alpha")
    venue_id, _org_id = await _link(client, db_session, headers)
    key = str(uuid4())
    body = {"post_type": "announcement", "body": "Doors at 10."}
    first = client.post(
        f"/v1/venues/{venue_id}/official-posts",
        headers=_idem(headers, key),
        json=body,
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/v1/venues/{venue_id}/official-posts",
        headers=_idem(headers, key),
        json=body,
    )
    assert second.status_code == 201, second.text
    assert first.json()["data"]["post"]["post_id"] == second.json()["data"]["post"]["post_id"]
    payload = second.json()["data"]["post"]
    assert payload["is_official"] is True
    assert "created_by_user_id" not in payload
    assert "attribution_mode" not in payload
