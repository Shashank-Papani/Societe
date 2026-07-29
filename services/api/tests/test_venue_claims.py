"""Phase 7A venue claim HTTP integration tests."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from organization_support import (
    auth_headers,
    claimable_venue,
    unlink_venue,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import VenueOrganization


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _org_name() -> str:
    return f"Claim Org {uuid4().hex[:10]}"


def _create_org(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/v1/organizations",
        headers=_idem(headers),
        json={"name": _org_name()},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _submit_claim(
    client: TestClient,
    headers: dict[str, str],
    venue_id: UUID,
    *,
    organization_id: str | None = None,
    requested_organization_name: str | None = None,
    evidence_reference: str | None = None,
    business_email: str | None = None,
    justification: str | None = None,
):
    body: dict[str, object] = {}
    if organization_id is not None:
        body["organization_id"] = organization_id
    if requested_organization_name is not None:
        body["requested_organization_name"] = requested_organization_name
    if evidence_reference is not None:
        body["evidence_reference"] = evidence_reference
    if business_email is not None:
        body["business_email"] = business_email
    if justification is not None:
        body["justification"] = justification
    return client.post(
        f"/v1/venues/{venue_id}/claims",
        headers=_idem(headers),
        json=body,
    )


@pytest.mark.asyncio
async def test_submit_venue_claim(client: TestClient, db_session: AsyncSession) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue = await claimable_venue(db_session)

    response = _submit_claim(
        client,
        headers,
        venue.id,
        organization_id=org_id,
        justification="We operate this venue.",
        evidence_reference="s3://private/evidence/lease.pdf",
        business_email="ops@example.test",
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["venue_id"] == str(venue.id)
    assert data["status"] == "pending"
    assert data["organization_id"] == org_id
    assert "evidence_reference" not in data
    assert "business_email" not in data

    # Cancel so the venue stays claimable for later tests.
    cancel = client.post(f"/v1/venue-claims/{data['id']}/cancel", headers=headers)
    assert cancel.status_code == 200, cancel.text


@pytest.mark.asyncio
async def test_duplicate_pending_claim_rejected(
    client: TestClient, db_session: AsyncSession
) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue = await claimable_venue(db_session)

    first = _submit_claim(client, headers, venue.id, organization_id=org_id)
    second = _submit_claim(client, headers, venue.id, organization_id=org_id)
    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "CLAIM_ALREADY_PENDING"

    client.post(f"/v1/venue-claims/{first.json()['data']['id']}/cancel", headers=headers)


@pytest.mark.asyncio
async def test_ordinary_user_cannot_approve_when_admin_flag_off(
    client: TestClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings
    from app.db.session import reset_resource_globals
    from app.main import create_app

    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue = await claimable_venue(db_session)
    submitted = _submit_claim(client, headers, venue.id, organization_id=org_id)
    assert submitted.status_code == 201, submitted.text
    claim_id = submitted.json()["data"]["id"]

    monkeypatch.setenv("FF_VENUE_CLAIM_ADMIN", "false")
    get_settings.cache_clear()
    reset_resource_globals()
    with TestClient(create_app()) as disabled:
        token = disabled.post("/v1/auth/local/token", json={"persona": "alpha"}).json()["data"][
            "access_token"
        ]
        response = disabled.post(
            f"/v1/admin/venue-claims/{claim_id}/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404, response.text

    get_settings.cache_clear()
    reset_resource_globals()
    client.post(f"/v1/venue-claims/{claim_id}/cancel", headers=headers)


@pytest.mark.asyncio
async def test_flag_on_alpha_may_approve_claim(
    client: TestClient, db_session: AsyncSession
) -> None:
    alpha = auth_headers(client, persona="alpha")
    org_id = _create_org(client, alpha)
    venue = await claimable_venue(db_session)
    submitted = _submit_claim(client, alpha, venue.id, organization_id=org_id)
    assert submitted.status_code == 201, submitted.text
    claim_id = submitted.json()["data"]["id"]

    approved = client.post(f"/v1/admin/venue-claims/{claim_id}/approve", headers=alpha)
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "approved"

    await unlink_venue(db_session, venue.id)


@pytest.mark.asyncio
async def test_flag_on_beta_cannot_approve_claim(
    client: TestClient, db_session: AsyncSession
) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    venue = await claimable_venue(db_session)
    submitted = _submit_claim(client, alpha, venue.id, organization_id=org_id)
    assert submitted.status_code == 201, submitted.text
    claim_id = submitted.json()["data"]["id"]

    denied = client.post(f"/v1/admin/venue-claims/{claim_id}/approve", headers=beta)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"

    client.post(f"/v1/venue-claims/{claim_id}/cancel", headers=alpha)


@pytest.mark.asyncio
async def test_flag_on_arbitrary_local_user_cannot_approve_claim(
    client: TestClient, db_session: AsyncSession
) -> None:
    alpha = auth_headers(client, persona="alpha")
    org_id = _create_org(client, alpha)
    venue = await claimable_venue(db_session)
    submitted = _submit_claim(client, alpha, venue.id, organization_id=org_id)
    assert submitted.status_code == 201, submitted.text
    claim_id = submitted.json()["data"]["id"]

    # Default local token uses LOCAL_DEV_SUBJECT — not allowlisted.
    local = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    denied = client.post(
        f"/v1/admin/venue-claims/{claim_id}/approve",
        headers={"Authorization": f"Bearer {local}"},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"

    client.post(f"/v1/venue-claims/{claim_id}/cancel", headers=alpha)


@pytest.mark.asyncio
async def test_flag_on_beta_cannot_reject_claim(
    client: TestClient, db_session: AsyncSession
) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    venue = await claimable_venue(db_session)
    submitted = _submit_claim(client, alpha, venue.id, organization_id=org_id)
    assert submitted.status_code == 201, submitted.text
    claim_id = submitted.json()["data"]["id"]

    denied = client.post(
        f"/v1/admin/venue-claims/{claim_id}/reject",
        headers=beta,
        json={"reason": "Beta should not review claims."},
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "FORBIDDEN"

    client.post(f"/v1/venue-claims/{claim_id}/cancel", headers=alpha)


def test_unauthenticated_caller_cannot_approve_claim(client: TestClient) -> None:
    response = client.post(f"/v1/admin/venue-claims/{uuid4()}/approve")
    assert response.status_code == 401, response.text


def test_staging_and_production_reject_venue_claim_admin_flag() -> None:
    from pydantic import ValidationError

    from app.core.config import Settings

    for env in ("staging", "production"):
        with pytest.raises(ValidationError, match="FF_VENUE_CLAIM_ADMIN"):
            Settings(
                app_env=env,
                auth_provider="cognito",
                ff_venue_claim_admin=True,
                ff_location_simulator=False,
                media_malware_scanner="clamav",
                media_moderation_provider="rekognition",
                email_provider="ses",
                ses_from_email="noreply@example.com",
            )


def test_dev_venue_claim_admin_allowlist_is_alpha_only() -> None:
    from app.modules.identity.dev_personas import (
        DEV_PERSONAS,
        DEV_VENUE_CLAIM_ADMIN_SUBJECTS,
    )

    assert DEV_VENUE_CLAIM_ADMIN_SUBJECTS == frozenset({"dev-user-alpha"})
    assert DEV_PERSONAS["beta"].subject not in DEV_VENUE_CLAIM_ADMIN_SUBJECTS


@pytest.mark.asyncio
async def test_admin_approve_links_organization_and_venue(
    client: TestClient, db_session: AsyncSession
) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue = await claimable_venue(db_session)
    submitted = _submit_claim(client, headers, venue.id, organization_id=org_id)
    assert submitted.status_code == 201, submitted.text
    claim_id = submitted.json()["data"]["id"]

    approved = client.post(f"/v1/admin/venue-claims/{claim_id}/approve", headers=headers)
    assert approved.status_code == 200, approved.text
    data = approved.json()["data"]
    assert data["status"] == "approved"
    assert data["organization_id"] == org_id

    link = await db_session.execute(
        select(VenueOrganization).where(
            VenueOrganization.venue_id == venue.id,
            VenueOrganization.status == "active",
        )
    )
    row = link.scalar_one()
    assert str(row.organization_id) == org_id
    assert str(row.approved_claim_id) == claim_id

    await unlink_venue(db_session, venue.id)


@pytest.mark.asyncio
async def test_double_approve_is_idempotent(client: TestClient, db_session: AsyncSession) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue = await claimable_venue(db_session)
    submitted = _submit_claim(client, headers, venue.id, organization_id=org_id)
    claim_id = submitted.json()["data"]["id"]

    first = client.post(f"/v1/admin/venue-claims/{claim_id}/approve", headers=headers)
    second = client.post(f"/v1/admin/venue-claims/{claim_id}/approve", headers=headers)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["data"]["status"] == "approved"
    assert second.json()["data"]["status"] == "approved"
    assert first.json()["data"]["id"] == second.json()["data"]["id"]

    await unlink_venue(db_session, venue.id)


@pytest.mark.asyncio
async def test_reject_then_cannot_approve(client: TestClient, db_session: AsyncSession) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue = await claimable_venue(db_session)
    submitted = _submit_claim(client, headers, venue.id, organization_id=org_id)
    claim_id = submitted.json()["data"]["id"]

    rejected = client.post(
        f"/v1/admin/venue-claims/{claim_id}/reject",
        headers=headers,
        json={"reason": "Insufficient evidence provided."},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["data"]["status"] == "rejected"

    approve = client.post(f"/v1/admin/venue-claims/{claim_id}/approve", headers=headers)
    assert approve.status_code == 409, approve.text
    assert approve.json()["error"]["code"] == "CLAIM_ALREADY_FINALIZED"


@pytest.mark.asyncio
async def test_evidence_omitted_from_public_projection(
    client: TestClient, db_session: AsyncSession
) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    venue = await claimable_venue(db_session)
    evidence = f"private-evidence-{uuid4().hex}"
    submitted = _submit_claim(
        client,
        headers,
        venue.id,
        organization_id=org_id,
        evidence_reference=evidence,
        business_email="secret@example.test",
        justification="Ownership docs attached.",
    )
    assert submitted.status_code == 201, submitted.text
    claim = submitted.json()["data"]
    assert "evidence_reference" not in claim
    assert "business_email" not in claim
    assert evidence not in submitted.text

    listed = client.get("/v1/me/venue-claims", headers=headers)
    assert listed.status_code == 200, listed.text
    body = listed.text
    assert evidence not in body
    assert "secret@example.test" not in body
    for item in listed.json()["data"]["items"]:
        assert "evidence_reference" not in item
        assert "business_email" not in item

    client.post(f"/v1/venue-claims/{claim['id']}/cancel", headers=headers)


@pytest.mark.asyncio
async def test_one_active_managing_organization(
    client: TestClient, db_session: AsyncSession
) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_a = _create_org(client, alpha)
    org_b = _create_org(client, beta)
    venue = await claimable_venue(db_session)

    submitted = _submit_claim(client, alpha, venue.id, organization_id=org_a)
    assert submitted.status_code == 201, submitted.text
    claim_id = submitted.json()["data"]["id"]
    approved = client.post(f"/v1/admin/venue-claims/{claim_id}/approve", headers=alpha)
    assert approved.status_code == 200, approved.text

    second = _submit_claim(client, beta, venue.id, organization_id=org_b)
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "VENUE_ALREADY_CLAIMED"

    # Unique partial index: only one active managing org per venue.
    venue_id = venue.id
    try:
        async with db_session.begin_nested():
            db_session.add(
                VenueOrganization(
                    venue_id=venue_id,
                    organization_id=UUID(org_b),
                    status="active",
                )
            )
            await db_session.flush()
        pytest.fail("expected unique active venue organization violation")
    except IntegrityError:
        pass

    await unlink_venue(db_session, venue_id)
