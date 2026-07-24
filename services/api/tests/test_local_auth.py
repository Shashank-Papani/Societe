from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError


def test_local_token_and_me(client: TestClient) -> None:
    token_response = client.post("/v1/auth/local/token", json={})
    assert token_response.status_code == 200
    token_body = token_response.json()
    assert token_body["error"] is None
    access_token = token_body["data"]["access_token"]
    assert token_body["data"]["subject"] == "local-dev-user"

    me_response = client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_response.status_code == 200
    me_body = me_response.json()
    assert me_body["data"]["subject"] == "local-dev-user"
    assert me_body["data"]["handle"] == "localdev"
    assert me_body["data"]["auth_provider"] == "local"


def test_me_requires_bearer(client: TestClient) -> None:
    response = client.get("/v1/me")
    assert response.status_code == 401
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_local_auth_rejected_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_PROVIDER", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-production-0123456789abcdef")
    from app.core.config import Settings, get_settings

    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        Settings()
    get_settings.cache_clear()
