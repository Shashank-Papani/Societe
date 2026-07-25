"""HTTP surface for Phase 4 Calling Cards."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def auth_header(client: TestClient) -> dict[str, str]:
    token = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_phase_four_routes_are_wired(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "get" in paths["/v1/venues/me/discoverable-users"]
    assert "post" in paths["/v1/calling-cards"]
    assert "get" in paths["/v1/calling-cards/inbox"]
    assert "get" in paths["/v1/calling-cards/sent"]
    assert "get" in paths["/v1/calling-cards/{calling_card_id}"]
    assert "get" in paths["/v1/calling-cards/{calling_card_id}/status"]
    assert "post" in paths["/v1/calling-cards/{calling_card_id}/respond"]
    assert "post" in paths["/v1/calling-cards/{calling_card_id}/cancel"]
    assert "post" in paths["/v1/calling-cards/{calling_card_id}/share"]
    assert "post" in paths["/v1/users/{user_id}/block"]
    assert "delete" in paths["/v1/users/{user_id}/block"]
    assert "post" in paths["/v1/events/{event_id}/ack"]


def test_calling_card_routes_refuse_anonymous(client: TestClient) -> None:
    card_id = uuid4()
    user_id = uuid4()
    responses = (
        client.get("/v1/venues/me/discoverable-users"),
        client.post(
            "/v1/calling-cards",
            json={"recipient_user_id": str(user_id)},
            headers={"Idempotency-Key": str(uuid4())},
        ),
        client.get("/v1/calling-cards/inbox"),
        client.get("/v1/calling-cards/sent"),
        client.get(f"/v1/calling-cards/{card_id}"),
        client.get(f"/v1/calling-cards/{card_id}/status"),
        client.post(
            f"/v1/calling-cards/{card_id}/respond",
            json={"decision": "decline"},
            headers={"Idempotency-Key": str(uuid4())},
        ),
        client.post(f"/v1/calling-cards/{card_id}/cancel"),
        client.post(f"/v1/calling-cards/{card_id}/share", json={"share_scopes": []}),
        client.post(f"/v1/users/{user_id}/block", json={}),
        client.delete(f"/v1/users/{user_id}/block"),
    )
    for response in responses:
        assert response.status_code == 401, response.text


def test_create_requires_idempotency_key(client: TestClient) -> None:
    headers = auth_header(client)
    response = client.post(
        "/v1/calling-cards",
        headers=headers,
        json={"recipient_user_id": str(uuid4())},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_unknown_body_fields_are_rejected(client: TestClient) -> None:
    headers = {**auth_header(client), "Idempotency-Key": str(uuid4())}
    response = client.post(
        "/v1/calling-cards",
        headers=headers,
        json={"recipient_user_id": str(uuid4()), "venue_id": str(uuid4())},
    )
    assert response.status_code == 422


def test_feature_flag_disables_surface(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings
    from app.db.session import reset_resource_globals
    from app.main import create_app

    monkeypatch.setenv("FF_CALLING_CARDS", "false")
    get_settings.cache_clear()
    reset_resource_globals()
    with TestClient(create_app()) as disabled:
        token = disabled.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
        response = disabled.post(
            "/v1/calling-cards",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": str(uuid4()),
            },
            json={"recipient_user_id": str(uuid4())},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "CALLING_CARDS_DISABLED"
    get_settings.cache_clear()
    reset_resource_globals()
