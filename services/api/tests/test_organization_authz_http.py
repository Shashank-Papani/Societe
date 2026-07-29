"""Phase 7A organization authorization over HTTP (membership / venue linkage)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from organization_support import (
    attach_email,
    auth_headers,
    claimable_venue,
    me,
    unlink_venue,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Organization, OrganizationMember, VenueOrganization


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _org_name() -> str:
    return f"Authz Org {uuid4().hex[:10]}"


def _email(prefix: str = "authz") -> str:
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


@pytest.mark.asyncio
async def test_suspended_organization_is_rejected(
    client: TestClient, db_session: AsyncSession
) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)

    org = await db_session.get(Organization, UUID(org_id))
    assert org is not None
    org.status = "suspended"
    org.updated_at = datetime.now(UTC)
    await db_session.commit()

    response = client.get(f"/v1/organizations/{org_id}/members", headers=headers)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "ORGANIZATION_INACTIVE"

    invite = client.post(
        f"/v1/organizations/{org_id}/invitations",
        headers=_idem(headers),
        json={"email": _email(), "role": "manager"},
    )
    assert invite.status_code == 403, invite.text
    assert invite.json()["error"]["code"] == "ORGANIZATION_INACTIVE"


@pytest.mark.asyncio
async def test_removed_member_is_rejected(client: TestClient, db_session: AsyncSession) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    email = _email("removed")
    invited = client.post(
        f"/v1/organizations/{org_id}/invitations",
        headers=_idem(alpha),
        json={"email": email, "role": "manager"},
    )
    assert invited.status_code == 201, invited.text
    beta_id = UUID(me(client, beta)["id"])
    await attach_email(db_session, user_id=beta_id, email=email)
    accepted = client.post(
        f"/v1/organization-invitations/{invited.json()['data']['token']}/accept",
        headers=beta,
    )
    assert accepted.status_code == 200, accepted.text

    removed = client.delete(
        f"/v1/organizations/{org_id}/members/{beta_id}",
        headers=alpha,
    )
    assert removed.status_code == 200, removed.text

    denied = client.get(f"/v1/organizations/{org_id}", headers=beta)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "ORGANIZATION_FORBIDDEN"


@pytest.mark.asyncio
async def test_unlinked_venue_is_rejected(client: TestClient, db_session: AsyncSession) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue_id = await _link_venue(client, db_session, headers, org_id)

    await unlink_venue(db_session, venue_id)

    response = client.patch(
        f"/v1/venues/{venue_id}/managed-profile",
        headers=headers,
        json={"description": "Should fail"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "VENUE_NOT_MANAGED"

    cover = client.put(
        f"/v1/venues/{venue_id}/cover",
        headers=_idem(headers),
        json={"media_asset_id": str(uuid4())},
    )
    assert cover.status_code == 403, cover.text
    assert cover.json()["error"]["code"] == "VENUE_NOT_MANAGED"


@pytest.mark.asyncio
async def test_cross_org_access_is_rejected(client: TestClient, db_session: AsyncSession) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_a = _create_org(client, alpha)
    org_b = _create_org(client, beta)
    venue_id = await _link_venue(client, db_session, alpha, org_a)

    # Beta is owner of org_b but not org_a / venue_a.
    denied_org = client.get(f"/v1/organizations/{org_a}", headers=beta)
    assert denied_org.status_code == 403, denied_org.text
    assert denied_org.json()["error"]["code"] == "ORGANIZATION_FORBIDDEN"

    denied_members = client.get(f"/v1/organizations/{org_a}/members", headers=beta)
    assert denied_members.status_code == 403, denied_members.text

    denied_profile = client.patch(
        f"/v1/venues/{venue_id}/managed-profile",
        headers=beta,
        json={"description": "Cross-org attempt"},
    )
    assert denied_profile.status_code == 403, denied_profile.text
    assert denied_profile.json()["error"]["code"] == "ORGANIZATION_FORBIDDEN"

    # Confirm venue is still linked only to org_a.
    link = await db_session.execute(
        select(VenueOrganization).where(
            VenueOrganization.venue_id == venue_id,
            VenueOrganization.status == "active",
        )
    )
    row = link.scalar_one()
    assert str(row.organization_id) == org_a
    assert str(row.organization_id) != org_b

    # Alpha cannot manage org_b either.
    denied_alpha = client.get(f"/v1/organizations/{org_b}/members", headers=alpha)
    assert denied_alpha.status_code == 403, denied_alpha.text

    await unlink_venue(db_session, venue_id)


@pytest.mark.asyncio
async def test_removed_membership_row_cannot_be_used(
    client: TestClient, db_session: AsyncSession
) -> None:
    """Direct DB removal also fails closed on subsequent org reads."""
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    email = _email("db-removed")
    invited = client.post(
        f"/v1/organizations/{org_id}/invitations",
        headers=_idem(alpha),
        json={"email": email, "role": "analyst"},
    )
    assert invited.status_code == 201, invited.text
    beta_id = UUID(me(client, beta)["id"])
    await attach_email(db_session, user_id=beta_id, email=email)
    assert (
        client.post(
            f"/v1/organization-invitations/{invited.json()['data']['token']}/accept",
            headers=beta,
        ).status_code
        == 200
    )

    result = await db_session.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == UUID(org_id),
            OrganizationMember.user_id == beta_id,
            OrganizationMember.status == "active",
        )
    )
    membership = result.scalar_one()
    membership.status = "removed"
    membership.removed_at = datetime.now(UTC)
    await db_session.commit()

    denied = client.get(f"/v1/organizations/{org_id}", headers=beta)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "ORGANIZATION_FORBIDDEN"
