"""HTTP surface for Phase 5 private messaging."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def auth_header(client: TestClient) -> dict[str, str]:
    token = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_messaging_routes_are_wired(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths["/v1/conversations"]
    assert "get" in paths["/v1/conversations"]
    assert "get" in paths["/v1/conversations/{conversation_id}"]
    assert "get" in paths["/v1/conversations/{conversation_id}/messages"]
    assert "post" in paths["/v1/conversations/{conversation_id}/messages"]
    assert "post" in paths["/v1/conversations/{conversation_id}/read"]
    assert "post" in paths["/v1/conversations/{conversation_id}/archive"]
    assert "post" in paths["/v1/conversations/{conversation_id}/unarchive"]


def test_messaging_routes_refuse_anonymous(client: TestClient) -> None:
    conversation_id = uuid4()
    responses = (
        client.post("/v1/conversations", json={"other_user_id": str(uuid4())}),
        client.get("/v1/conversations"),
        client.get(f"/v1/conversations/{conversation_id}"),
        client.get(f"/v1/conversations/{conversation_id}/messages"),
        client.post(
            f"/v1/conversations/{conversation_id}/messages",
            json={"body": "hi", "client_message_id": str(uuid4())},
        ),
        client.post(f"/v1/conversations/{conversation_id}/read", json={}),
        client.post(f"/v1/conversations/{conversation_id}/archive"),
        client.post(f"/v1/conversations/{conversation_id}/unarchive"),
    )
    for response in responses:
        assert response.status_code == 401, response.text


def test_idempotency_key_must_match_client_message_id(client: TestClient) -> None:
    headers = {
        **auth_header(client),
        "Idempotency-Key": str(uuid4()),
    }
    response = client.post(
        f"/v1/conversations/{uuid4()}/messages",
        headers=headers,
        json={"body": "hi", "client_message_id": str(uuid4())},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_MISMATCH"


def test_feature_flag_disables_messaging(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings
    from app.db.session import reset_resource_globals
    from app.main import create_app

    monkeypatch.setenv("FF_PRIVATE_MESSAGING", "false")
    get_settings.cache_clear()
    reset_resource_globals()
    with TestClient(create_app()) as disabled:
        token = disabled.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
        response = disabled.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "FEATURE_DISABLED"
