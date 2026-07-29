"""Phase 7A venue cover selection HTTP integration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from organization_support import (
    attach_email,
    auth_headers,
    claimable_venue,
    insert_venue_owned_media,
    me,
    unlink_venue,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CheckIn,
    MediaAsset,
    OutboxEvent,
    UserDevice,
    VenueAuditEvent,
)


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _org_name() -> str:
    return f"Cover Org {uuid4().hex[:10]}"


def _email(prefix: str = "cover") -> str:
    return f"{prefix}-{uuid4().hex[:10]}@example.test"


def _create_org(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/v1/organizations",
        headers=_idem(headers),
        json={"name": _org_name()},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


async def _link_venue(
    client: TestClient,
    db_session: AsyncSession,
    headers: dict[str, str],
    org_id: str,
) -> UUID:
    venue = await claimable_venue(db_session)
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
    return venue.id


def _set_cover(
    client: TestClient,
    headers: dict[str, str],
    venue_id: UUID,
    media_asset_id: UUID,
):
    return client.put(
        f"/v1/venues/{venue_id}/cover",
        headers=_idem(headers),
        json={"media_asset_id": str(media_asset_id)},
    )


async def _insert_live_vibe_asset(
    session: AsyncSession,
    *,
    venue_id: UUID,
    owner_user_id: UUID,
) -> MediaAsset:
    now = datetime.now(UTC)

    # Only one active check-in per user is allowed; close any leftover.
    active = await session.execute(
        select(CheckIn).where(
            CheckIn.user_id == owner_user_id,
            CheckIn.state.in_(("provisional", "verified", "rechecking", "degraded")),
        )
    )
    for row in active.scalars().all():
        row.exited_at = now
        row.state = "exited"
        row.exit_reason = "test_cleanup"
    await session.flush()

    device = UserDevice(
        user_id=owner_user_id,
        platform="ios",
        installation_id=uuid4(),
    )
    session.add(device)
    await session.flush()

    check_in = CheckIn(
        user_id=owner_user_id,
        venue_id=venue_id,
        state="verified",
        verification_level="standard",
        confidence_score=90,
        entry_method="fused_location",
        ghost_mode_snapshot=False,
        discoverable_snapshot=True,
        entered_at=now - timedelta(minutes=5),
        verified_at=now - timedelta(minutes=5),
        last_verified_at=now - timedelta(minutes=1),
        verified_until=now + timedelta(minutes=10),
        grace_until=now + timedelta(minutes=15),
        lease_expires_at=now + timedelta(minutes=15),
        geofence_version=1,
    )
    session.add(check_in)
    await session.flush()

    asset = MediaAsset(
        owner_user_id=owner_user_id,
        venue_id=venue_id,
        purpose="live_vibe",
        organization_id=None,
        author_check_in_id=check_in.id,
        device_id=device.id,
        media_type="image",
        lifecycle_status="ready",
        moderation_status="approved",
        attribution_mode="attributed",
        quarantine_object_key=f"live-vibe/{uuid4()}.jpg",
        declared_mime_type="image/jpeg",
        declared_byte_size=12_345,
        intent_expires_at=now + timedelta(hours=1),
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


@pytest.mark.asyncio
async def test_select_approved_venue_owned_cover(
    client: TestClient, db_session: AsyncSession
) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue_id = await _link_venue(client, db_session, headers, org_id)
    owner_id = UUID(me(client, headers)["id"])
    asset = await insert_venue_owned_media(
        db_session,
        venue_id=venue_id,
        organization_id=UUID(org_id),
        owner_user_id=owner_id,
    )

    response = _set_cover(client, headers, venue_id, asset.id)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["cover_media_id"] == str(asset.id)

    await unlink_venue(db_session, venue_id)


@pytest.mark.asyncio
async def test_reject_live_vibe_purpose_as_cover(
    client: TestClient, db_session: AsyncSession
) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue_id = await _link_venue(client, db_session, headers, org_id)
    owner_id = UUID(me(client, headers)["id"])
    asset = await _insert_live_vibe_asset(db_session, venue_id=venue_id, owner_user_id=owner_id)

    response = _set_cover(client, headers, venue_id, asset.id)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "COVER_MEDIA_INVALID"

    await unlink_venue(db_session, venue_id)


@pytest.mark.asyncio
async def test_reject_pending_and_rejected_media(
    client: TestClient, db_session: AsyncSession
) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue_id = await _link_venue(client, db_session, headers, org_id)
    owner_id = UUID(me(client, headers)["id"])

    pending = await insert_venue_owned_media(
        db_session,
        venue_id=venue_id,
        organization_id=UUID(org_id),
        owner_user_id=owner_id,
        moderation_status="pending",
    )
    rejected = await insert_venue_owned_media(
        db_session,
        venue_id=venue_id,
        organization_id=UUID(org_id),
        owner_user_id=owner_id,
        moderation_status="rejected",
    )

    for asset in (pending, rejected):
        response = _set_cover(client, headers, venue_id, asset.id)
        assert response.status_code == 400, response.text
        assert response.json()["error"]["code"] == "COVER_MEDIA_INVALID"

    await unlink_venue(db_session, venue_id)


@pytest.mark.asyncio
async def test_reject_cover_media_for_wrong_venue(
    client: TestClient, db_session: AsyncSession
) -> None:
    from app.db.models import Venue

    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue_id = await _link_venue(client, db_session, headers, org_id)
    other_result = await db_session.execute(
        select(Venue)
        .where(Venue.status == "active", Venue.id != venue_id)
        .order_by(Venue.name)
        .limit(1)
    )
    other = other_result.scalar_one_or_none()
    if other is None:
        pytest.skip("Need at least two active venues for wrong-venue cover test")
    owner_id = UUID(me(client, headers)["id"])
    asset = await insert_venue_owned_media(
        db_session,
        venue_id=other.id,
        organization_id=UUID(org_id),
        owner_user_id=owner_id,
    )

    response = _set_cover(client, headers, venue_id, asset.id)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "COVER_MEDIA_INVALID"

    await unlink_venue(db_session, venue_id)


@pytest.mark.asyncio
async def test_content_editor_can_select_cover(
    client: TestClient, db_session: AsyncSession
) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    venue_id = await _link_venue(client, db_session, alpha, org_id)

    email = _email("editor")
    invited = client.post(
        f"/v1/organizations/{org_id}/invitations",
        headers=_idem(alpha),
        json={"email": email, "role": "content_editor"},
    )
    assert invited.status_code == 201, invited.text
    await attach_email(db_session, user_id=UUID(me(client, beta)["id"]), email=email)
    accepted = client.post(
        f"/v1/organization-invitations/{invited.json()['data']['token']}/accept",
        headers=beta,
    )
    assert accepted.status_code == 200, accepted.text

    asset = await insert_venue_owned_media(
        db_session,
        venue_id=venue_id,
        organization_id=UUID(org_id),
        owner_user_id=UUID(me(client, alpha)["id"]),
    )
    response = _set_cover(client, beta, venue_id, asset.id)
    assert response.status_code == 200, response.text

    await unlink_venue(db_session, venue_id)


@pytest.mark.asyncio
async def test_analyst_cannot_select_cover(client: TestClient, db_session: AsyncSession) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    venue_id = await _link_venue(client, db_session, alpha, org_id)

    email = _email("analyst")
    invited = client.post(
        f"/v1/organizations/{org_id}/invitations",
        headers=_idem(alpha),
        json={"email": email, "role": "analyst"},
    )
    assert invited.status_code == 201, invited.text
    await attach_email(db_session, user_id=UUID(me(client, beta)["id"]), email=email)
    assert (
        client.post(
            f"/v1/organization-invitations/{invited.json()['data']['token']}/accept",
            headers=beta,
        ).status_code
        == 200
    )

    asset = await insert_venue_owned_media(
        db_session,
        venue_id=venue_id,
        organization_id=UUID(org_id),
        owner_user_id=UUID(me(client, alpha)["id"]),
    )
    response = _set_cover(client, beta, venue_id, asset.id)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "ORGANIZATION_FORBIDDEN"

    await unlink_venue(db_session, venue_id)


@pytest.mark.asyncio
async def test_remove_cover_restores_null(client: TestClient, db_session: AsyncSession) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue_id = await _link_venue(client, db_session, headers, org_id)
    asset = await insert_venue_owned_media(
        db_session,
        venue_id=venue_id,
        organization_id=UUID(org_id),
        owner_user_id=UUID(me(client, headers)["id"]),
    )
    assert _set_cover(client, headers, venue_id, asset.id).status_code == 200

    removed = client.delete(f"/v1/venues/{venue_id}/cover", headers=headers)
    assert removed.status_code == 200, removed.text
    assert removed.json()["data"]["cover_media_id"] is None

    detail = client.get(f"/v1/venues/{venue_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["cover_media_id"] is None

    await unlink_venue(db_session, venue_id)


@pytest.mark.asyncio
async def test_public_venue_detail_exposes_cover_media_id(
    client: TestClient, db_session: AsyncSession
) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue_id = await _link_venue(client, db_session, headers, org_id)
    asset = await insert_venue_owned_media(
        db_session,
        venue_id=venue_id,
        organization_id=UUID(org_id),
        owner_user_id=UUID(me(client, headers)["id"]),
    )
    assert _set_cover(client, headers, venue_id, asset.id).status_code == 200

    detail = client.get(f"/v1/venues/{venue_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["cover_media_id"] == str(asset.id)
    assert "cover_image_url" in data

    await unlink_venue(db_session, venue_id)


@pytest.mark.asyncio
async def test_cover_update_writes_audit_and_outbox_atomically(
    client: TestClient, db_session: AsyncSession
) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue_id = await _link_venue(client, db_session, headers, org_id)
    asset = await insert_venue_owned_media(
        db_session,
        venue_id=venue_id,
        organization_id=UUID(org_id),
        owner_user_id=UUID(me(client, headers)["id"]),
    )
    assert _set_cover(client, headers, venue_id, asset.id).status_code == 200

    audit = await db_session.execute(
        select(VenueAuditEvent).where(
            VenueAuditEvent.venue_id == venue_id,
            VenueAuditEvent.event_type == "venue.cover_selected",
            VenueAuditEvent.target_id == asset.id,
        )
    )
    assert audit.scalar_one_or_none() is not None

    outbox = await db_session.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.aggregate_id == venue_id,
            OutboxEvent.event_type == "venue.cover.changed",
        )
        .order_by(OutboxEvent.occurred_at.desc())
    )
    payloads = [event.payload for event in outbox.scalars().all()]
    assert any(payload.get("media_asset_id") == str(asset.id) for payload in payloads)

    await unlink_venue(db_session, venue_id)
