"""Phase 7A organization create / membership HTTP integration tests."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from organization_support import auth_headers, me


def _idem(headers: dict[str, str]) -> dict[str, str]:
    return {**headers, "Idempotency-Key": str(uuid4())}


def _org_name() -> str:
    return f"Org {uuid4().hex[:10]}"


@pytest.mark.asyncio
async def test_create_organization(client: TestClient) -> None:
    headers = auth_headers(client, persona="alpha")
    name = _org_name()
    response = client.post(
        "/v1/organizations",
        headers=_idem(headers),
        json={"name": name},
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["name"] == name
    assert data["status"] == "active"
    assert data["role"] == "owner"
    assert data["id"]

    profile = me(client, headers)
    listed = client.get("/v1/me/organizations", headers=headers)
    assert listed.status_code == 200
    ids = {item["organization"]["id"] for item in listed.json()["data"]["items"]}
    assert data["id"] in ids
    assert profile["id"]


@pytest.mark.asyncio
async def test_create_organization_idempotent(client: TestClient) -> None:
    headers = auth_headers(client, persona="alpha")
    key = str(uuid4())
    body = {"name": _org_name()}
    first = client.post(
        "/v1/organizations",
        headers={**headers, "Idempotency-Key": key},
        json=body,
    )
    second = client.post(
        "/v1/organizations",
        headers={**headers, "Idempotency-Key": key},
        json=body,
    )
    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["data"] == second.json()["data"]


@pytest.mark.asyncio
async def test_create_organization_rejects_unknown_fields(client: TestClient) -> None:
    headers = auth_headers(client, persona="alpha")
    response = client.post(
        "/v1/organizations",
        headers=_idem(headers),
        json={"name": _org_name(), "extra_field": "nope"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_organization_requires_auth(client: TestClient) -> None:
    response = client.post(
        "/v1/organizations",
        headers={"Idempotency-Key": str(uuid4())},
        json={"name": _org_name()},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_members_after_create(client: TestClient) -> None:
    headers = auth_headers(client, persona="alpha")
    created = client.post(
        "/v1/organizations",
        headers=_idem(headers),
        json={"name": _org_name()},
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["data"]["id"]
    alpha_id = me(client, headers)["id"]

    members = client.get(f"/v1/organizations/{org_id}/members", headers=headers)
    assert members.status_code == 200, members.text
    items = members.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["user_id"] == alpha_id
    assert items[0]["role"] == "owner"
    assert items[0]["handle"] == "devalpha"


@pytest.mark.asyncio
async def test_cannot_remove_last_owner(client: TestClient) -> None:
    headers = auth_headers(client, persona="alpha")
    created = client.post(
        "/v1/organizations",
        headers=_idem(headers),
        json={"name": _org_name()},
    )
    assert created.status_code == 201, created.text
    org_id = created.json()["data"]["id"]
    alpha_id = me(client, headers)["id"]

    removed = client.delete(
        f"/v1/organizations/{org_id}/members/{alpha_id}",
        headers=headers,
    )
    assert removed.status_code == 409, removed.text
    assert removed.json()["error"]["code"] == "LAST_OWNER_PROTECTED"
