from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient


def _token(client: TestClient) -> str:
    return client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]


def _mint_subject_token(subject: str) -> str:
    from app.core.config import get_settings
    from app.core.security import create_access_token
    from app.db.session import get_session_factory, reset_resource_globals
    from app.modules.identity.service import IdentityService

    async def _run() -> str:
        settings = get_settings()
        factory = get_session_factory(settings)
        async with factory() as session:
            service = IdentityService(session)
            user = await service.resolve_or_provision(subject)
            await session.commit()
            return create_access_token(
                subject=user.auth_subject,
                handle=user.handle,
                settings=settings,
            )

    reset_resource_globals()
    try:
        return asyncio.run(_run())
    finally:
        reset_resource_globals()


def test_device_registration_requires_idempotency_key(client: TestClient) -> None:
    token = _token(client)
    response = client.post(
        "/v1/me/devices",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "platform": "ios",
            "installation_id": str(uuid.uuid4()),
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_device_upsert_and_no_silent_transfer(client: TestClient) -> None:
    token = _token(client)
    installation_id = str(uuid.uuid4())
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": str(uuid.uuid4()),
    }
    first = client.post(
        "/v1/me/devices",
        headers=headers,
        json={"platform": "ios", "installation_id": installation_id, "app_version": "1.0.0"},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/v1/me/devices",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
        json={"platform": "ios", "installation_id": installation_id, "app_version": "1.0.1"},
    )
    assert second.status_code == 200
    assert second.json()["data"]["app_version"] == "1.0.1"

    other_token = _mint_subject_token(f"other-{uuid.uuid4()}")
    conflict = client.post(
        "/v1/me/devices",
        headers={
            "Authorization": f"Bearer {other_token}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
        json={"platform": "ios", "installation_id": installation_id},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "DEVICE_ALREADY_REGISTERED"


def test_account_deletion_idempotency_and_replay(client: TestClient) -> None:
    token = _mint_subject_token(f"delete-me-{uuid.uuid4()}")
    key = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": key}
    first = client.post(
        "/v1/me/account-deletion",
        headers=headers,
        json={"confirmation": "DELETE"},
    )
    assert first.status_code == 200
    assert first.json()["data"]["status"] == "scheduled"

    me = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 403
    assert me.json()["error"]["code"] == "ACCOUNT_INACTIVE"

    replay = client.post(
        "/v1/me/account-deletion",
        headers=headers,
        json={"confirmation": "DELETE"},
    )
    assert replay.status_code == 200
    assert replay.json()["data"]["status"] == "scheduled"

    again = client.post(
        "/v1/me/account-deletion",
        headers={
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": str(uuid.uuid4()),
        },
        json={"confirmation": "DELETE"},
    )
    assert again.status_code == 200
    assert again.json()["data"]["status"] == "already_requested"


def test_privacy_patch_optional_idempotency(client: TestClient) -> None:
    token = _token(client)
    response = client.patch(
        "/v1/me/privacy",
        headers={"Authorization": f"Bearer {token}"},
        json={"ghost_mode": True},
    )
    assert response.status_code == 200, response.text
    privacy = response.json()["data"]["privacy"]
    assert privacy["ghost_mode"] is True
    assert privacy["effective"]["ghost_mode_overrides"] is True
    assert privacy["effective"]["discoverable_in_venue"] is False
