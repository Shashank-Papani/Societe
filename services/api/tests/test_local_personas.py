"""Development persona selection for dual-simulator local auth."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.modules.identity.dev_personas import DEV_PERSONAS, resolve_dev_persona


def test_allowlist_maps_only_alpha_and_beta() -> None:
    alpha = resolve_dev_persona("alpha")
    beta = resolve_dev_persona("beta")
    assert alpha.subject == "dev-user-alpha"
    assert alpha.handle == "devalpha"
    assert alpha.display_name == "Dev Alpha"
    assert beta.subject == "dev-user-beta"
    assert beta.handle == "devbeta"
    assert beta.display_name == "Dev Beta"
    assert set(DEV_PERSONAS) == {"alpha", "beta"}


def test_unknown_persona_rejected_by_allowlist() -> None:
    from app.core.errors import AppError

    with pytest.raises(AppError) as exc:
        resolve_dev_persona("gamma")
    assert exc.value.code == "UNKNOWN_DEV_PERSONA"


def test_alpha_token_maps_only_to_dev_user_alpha(client: TestClient) -> None:
    response = client.post("/v1/auth/local/token", json={"persona": "alpha"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["subject"] == "dev-user-alpha"
    assert data["handle"] == "devalpha"
    assert data["persona"] == "alpha"

    me = client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["data"]["handle"] == "devalpha"
    assert me.json()["data"]["display_name"] == "Dev Alpha"


def test_beta_token_maps_only_to_dev_user_beta(client: TestClient) -> None:
    response = client.post("/v1/auth/local/token", json={"persona": "beta"})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["subject"] == "dev-user-beta"
    assert data["handle"] == "devbeta"
    assert data["persona"] == "beta"

    me = client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {data['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["data"]["handle"] == "devbeta"
    assert me.json()["data"]["display_name"] == "Dev Beta"


def test_unknown_persona_http_rejected(client: TestClient) -> None:
    response = client.post("/v1/auth/local/token", json={"persona": "gamma"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNKNOWN_DEV_PERSONA"


def test_omitted_persona_keeps_legacy_local_dev_user(client: TestClient) -> None:
    response = client.post("/v1/auth/local/token", json={})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["subject"] == "local-dev-user"
    assert data["handle"] == "localdev"
    assert data.get("persona") in (None,)


def test_persona_selection_unavailable_when_local_auth_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings
    from app.db.session import reset_resource_globals
    from app.main import create_app

    monkeypatch.setenv("AUTH_PROVIDER", "cognito")
    monkeypatch.setenv("COGNITO_REGION", "us-east-1")
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_example")
    monkeypatch.setenv("COGNITO_APP_CLIENT_ID", "exampleclientid")
    get_settings.cache_clear()
    reset_resource_globals()
    with TestClient(create_app()) as disabled:
        response = disabled.post("/v1/auth/local/token", json={"persona": "alpha"})
        assert response.status_code == 404
    get_settings.cache_clear()
    reset_resource_globals()


def test_alpha_and_beta_register_separate_devices(client: TestClient) -> None:
    alpha = client.post("/v1/auth/local/token", json={"persona": "alpha"}).json()["data"]
    beta = client.post("/v1/auth/local/token", json={"persona": "beta"}).json()["data"]

    alpha_install = str(uuid.uuid4())
    beta_install = str(uuid.uuid4())

    alpha_device = client.post(
        "/v1/me/devices",
        headers={
            "Authorization": f"Bearer {alpha['access_token']}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
        json={"platform": "ios", "installation_id": alpha_install},
    )
    assert alpha_device.status_code == 200, alpha_device.text

    beta_device = client.post(
        "/v1/me/devices",
        headers={
            "Authorization": f"Bearer {beta['access_token']}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
        json={"platform": "ios", "installation_id": beta_install},
    )
    assert beta_device.status_code == 200, beta_device.text
    assert alpha_device.json()["data"]["id"] != beta_device.json()["data"]["id"]

    # Alpha cannot reuse Beta's installation id.
    conflict = client.post(
        "/v1/me/devices",
        headers={
            "Authorization": f"Bearer {alpha['access_token']}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
        json={"platform": "ios", "installation_id": beta_install},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "DEVICE_ALREADY_REGISTERED"


def test_client_cannot_supply_arbitrary_subject(client: TestClient) -> None:
    response = client.post(
        "/v1/auth/local/token",
        json={"persona": "alpha", "subject": "evil", "handle": "hax"},
    )
    assert response.status_code == 422
