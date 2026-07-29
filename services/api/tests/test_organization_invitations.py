"""Phase 7A organization invitation HTTP integration tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from organization_support import attach_email, auth_headers, load_membership, me
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import OrganizationInvitation, VenueAuditEvent
from app.modules.identity.crypto_util import hash_secret


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _org_name() -> str:
    return f"Invite Org {uuid4().hex[:10]}"


def _email(prefix: str = "invitee") -> str:
    return f"{prefix}-{uuid4().hex[:10]}@example.test"


def _create_org(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/v1/organizations",
        headers=_idem(headers),
        json={"name": _org_name()},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _invite(
    client: TestClient,
    headers: dict[str, str],
    org_id: str,
    *,
    email: str,
    role: str,
) -> dict:
    response = client.post(
        f"/v1/organizations/{org_id}/invitations",
        headers=_idem(headers),
        json={"email": email, "role": role},
    )
    return response


@pytest.mark.asyncio
async def test_owner_can_invite_each_role(client: TestClient) -> None:
    headers = auth_headers(client, persona="alpha")
    org_id = _create_org(client, headers)
    for role in ("owner", "manager", "content_editor", "analyst"):
        response = _invite(client, headers, org_id, email=_email(role), role=role)
        assert response.status_code == 201, response.text
        data = response.json()["data"]
        assert data["role"] == role
        assert data["status"] == "pending"
        assert data["token"]


@pytest.mark.asyncio
async def test_manager_cannot_invite_owner(client: TestClient, db_session: AsyncSession) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    email = _email("manager")
    invited = _invite(client, alpha, org_id, email=email, role="manager")
    assert invited.status_code == 201, invited.text
    token = invited.json()["data"]["token"]

    beta_id = UUID(me(client, beta)["id"])
    await attach_email(db_session, user_id=beta_id, email=email)
    accepted = client.post(f"/v1/organization-invitations/{token}/accept", headers=beta)
    assert accepted.status_code == 200, accepted.text

    denied = _invite(client, beta, org_id, email=_email("owner-try"), role="owner")
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "ORGANIZATION_FORBIDDEN"


@pytest.mark.asyncio
async def test_content_editor_cannot_invite(client: TestClient, db_session: AsyncSession) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    email = _email("editor")
    invited = _invite(client, alpha, org_id, email=email, role="content_editor")
    assert invited.status_code == 201, invited.text
    token = invited.json()["data"]["token"]
    await attach_email(db_session, user_id=UUID(me(client, beta)["id"]), email=email)
    assert (
        client.post(f"/v1/organization-invitations/{token}/accept", headers=beta).status_code == 200
    )

    denied = _invite(client, beta, org_id, email=_email("editor-try"), role="analyst")
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "ORGANIZATION_FORBIDDEN"


@pytest.mark.asyncio
async def test_analyst_cannot_invite(client: TestClient, db_session: AsyncSession) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    email = _email("analyst")
    invited = _invite(client, alpha, org_id, email=email, role="analyst")
    assert invited.status_code == 201, invited.text
    token = invited.json()["data"]["token"]
    await attach_email(db_session, user_id=UUID(me(client, beta)["id"]), email=email)
    assert (
        client.post(f"/v1/organization-invitations/{token}/accept", headers=beta).status_code == 200
    )

    denied = _invite(client, beta, org_id, email=_email("analyst-try"), role="analyst")
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "ORGANIZATION_FORBIDDEN"


@pytest.mark.asyncio
async def test_accept_invitation_email_match(client: TestClient, db_session: AsyncSession) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    email = _email("match")
    invited = _invite(client, alpha, org_id, email=email, role="manager")
    assert invited.status_code == 201, invited.text
    token = invited.json()["data"]["token"]
    invitation_id = UUID(invited.json()["data"]["id"])

    beta_id = UUID(me(client, beta)["id"])
    await attach_email(db_session, user_id=beta_id, email=email)
    accepted = client.post(f"/v1/organization-invitations/{token}/accept", headers=beta)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["data"]["role"] == "manager"

    membership = await load_membership(db_session, organization_id=UUID(org_id), user_id=beta_id)
    assert membership is not None
    assert membership.role == "manager"

    row = await db_session.get(OrganizationInvitation, invitation_id)
    assert row is not None
    assert row.status == "accepted"


@pytest.mark.asyncio
async def test_accept_invitation_email_mismatch(
    client: TestClient, db_session: AsyncSession
) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    invited = _invite(client, alpha, org_id, email=_email("mismatch-target"), role="manager")
    assert invited.status_code == 201, invited.text
    token = invited.json()["data"]["token"]

    await attach_email(
        db_session,
        user_id=UUID(me(client, beta)["id"]),
        email=_email("other"),
    )
    denied = client.post(f"/v1/organization-invitations/{token}/accept", headers=beta)
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "INVITATION_EMAIL_MISMATCH"


@pytest.mark.asyncio
async def test_accept_expired_invitation(client: TestClient, db_session: AsyncSession) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    email = _email("expired")
    invited = _invite(client, alpha, org_id, email=email, role="analyst")
    assert invited.status_code == 201, invited.text
    token = invited.json()["data"]["token"]
    invitation_id = UUID(invited.json()["data"]["id"])

    row = await db_session.get(OrganizationInvitation, invitation_id)
    assert row is not None
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await db_session.commit()

    await attach_email(db_session, user_id=UUID(me(client, beta)["id"]), email=email)
    denied = client.post(f"/v1/organization-invitations/{token}/accept", headers=beta)
    assert denied.status_code == 404, denied.text
    assert denied.json()["error"]["code"] == "INVITATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_revoke_invitation_blocks_accept(
    client: TestClient, db_session: AsyncSession
) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    email = _email("revoke")
    invited = _invite(client, alpha, org_id, email=email, role="manager")
    assert invited.status_code == 201, invited.text
    token = invited.json()["data"]["token"]
    invitation_id = invited.json()["data"]["id"]

    revoked = client.post(
        f"/v1/organization-invitations/{invitation_id}/revoke",
        headers=alpha,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["data"]["status"] == "revoked"

    await attach_email(db_session, user_id=UUID(me(client, beta)["id"]), email=email)
    denied = client.post(f"/v1/organization-invitations/{token}/accept", headers=beta)
    assert denied.status_code == 404, denied.text


@pytest.mark.asyncio
async def test_duplicate_pending_invitation_rejected(client: TestClient) -> None:
    alpha = auth_headers(client, persona="alpha")
    org_id = _create_org(client, alpha)
    email = _email("dup")
    first = _invite(client, alpha, org_id, email=email, role="manager")
    second = _invite(client, alpha, org_id, email=email, role="analyst")
    assert first.status_code == 201, first.text
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "INVITATION_ALREADY_PENDING"


@pytest.mark.asyncio
async def test_invitation_stores_token_hash_only(
    client: TestClient, db_session: AsyncSession
) -> None:
    alpha = auth_headers(client, persona="alpha")
    org_id = _create_org(client, alpha)
    invited = _invite(client, alpha, org_id, email=_email("hash"), role="manager")
    assert invited.status_code == 201, invited.text
    data = invited.json()["data"]
    token = data["token"]
    invitation_id = UUID(data["id"])

    row = await db_session.get(OrganizationInvitation, invitation_id)
    assert row is not None
    assert row.token_hash == hash_secret(token, get_settings())
    assert token not in row.token_hash

    events = await db_session.execute(
        select(VenueAuditEvent).where(
            VenueAuditEvent.target_id == invitation_id,
            VenueAuditEvent.event_type == "membership.invited",
        )
    )
    for event in events.scalars().all():
        blob = str(event.metadata_json)
        assert token not in blob
        assert "token" not in event.metadata_json


@pytest.mark.asyncio
async def test_accept_invitation_twice_is_idempotent(
    client: TestClient, db_session: AsyncSession
) -> None:
    alpha = auth_headers(client, persona="alpha")
    beta = auth_headers(client, persona="beta")
    org_id = _create_org(client, alpha)
    email = _email("twice")
    invited = _invite(client, alpha, org_id, email=email, role="content_editor")
    assert invited.status_code == 201, invited.text
    token = invited.json()["data"]["token"]

    await attach_email(db_session, user_id=UUID(me(client, beta)["id"]), email=email)
    first = client.post(f"/v1/organization-invitations/{token}/accept", headers=beta)
    second = client.post(f"/v1/organization-invitations/{token}/accept", headers=beta)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["data"]["role"] == "content_editor"
    assert second.json()["data"]["role"] == "content_editor"
