"""The HTTP surface of Phase 3.

The service-level tests cover behaviour; this file covers the boundary — which
routes exist, what they demand before doing any work, and what the published
contract admits. The most important assertion here is a negative one: no
multipart upload route is reachable, because a half-built multipart flow is worse
than none at all.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

UPLOADS = "/v1/media/uploads"


def auth_header(client: TestClient) -> dict[str, str]:
    token = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def upload_body() -> dict[str, object]:
    return {
        "venue_id": str(uuid4()),
        "device_id": str(uuid4()),
        "media_type": "image",
        "mime_type": "image/jpeg",
        "byte_size": 120_000,
    }


# ---------------------------------------------------------------- registration


def test_the_phase_three_routes_are_wired(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths[UPLOADS]
    assert "post" in paths["/v1/media/uploads/{upload_id}/complete"]
    assert "get" in paths["/v1/media/uploads/{upload_id}"]
    assert "get" in paths["/v1/venues/{venue_id}/vibes"]
    assert "get" in paths["/v1/me/vibes"]
    assert "post" in paths["/v1/vibes/{vibe_id}/reports"]
    assert "delete" in paths["/v1/vibes/{vibe_id}"]


def test_no_multipart_upload_route_is_published(client: TestClient) -> None:
    """Phase 3 is single-PUT. A partial multipart flow must not look available."""
    paths = client.get("/openapi.json").json()["paths"]
    assert not [path for path in paths if "part" in path.lower()]

    schema = client.get("/openapi.json").json()["components"]["schemas"]
    upload_request = schema["CreateUploadRequest"]["properties"]
    assert "parts" not in upload_request
    assert "part_count" not in upload_request


def test_the_contract_never_exposes_an_object_key(client: TestClient) -> None:
    body = client.get("/openapi.json").text
    assert "object_key" not in body
    assert "quarantine_object_key" not in body


# ----------------------------------------------------------------------- auth


def test_every_route_refuses_an_anonymous_caller(client: TestClient) -> None:
    vibe_id = uuid4()
    unauthenticated = (
        client.post(UPLOADS, json=upload_body(), headers={"Idempotency-Key": str(uuid4())}),
        client.post(f"{UPLOADS}/{uuid4()}/complete", json={"device_id": str(uuid4())}),
        client.get(f"{UPLOADS}/{uuid4()}"),
        client.get(f"/v1/venues/{uuid4()}/vibes"),
        client.get("/v1/me/vibes"),
        client.post(f"/v1/vibes/{vibe_id}/reports", json={"reason": "spam"}),
        client.delete(f"/v1/vibes/{vibe_id}"),
    )
    for response in unauthenticated:
        assert response.status_code == 401, response.text


# --------------------------------------------------------------- request shape


def test_an_upload_intent_requires_an_idempotency_key(client: TestClient) -> None:
    response = client.post(UPLOADS, json=upload_body(), headers=auth_header(client))
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_unknown_body_fields_are_rejected_rather_than_ignored(client: TestClient) -> None:
    """A client that starts sending multipart fields should hear about it."""
    headers = {**auth_header(client), "Idempotency-Key": str(uuid4())}
    response = client.post(
        UPLOADS,
        json={**upload_body(), "parts": 4},
        headers=headers,
    )
    assert response.status_code == 422


def test_an_unsupported_media_type_is_refused_before_any_url_is_minted(
    client: TestClient,
) -> None:
    headers = {**auth_header(client), "Idempotency-Key": str(uuid4())}
    response = client.post(
        UPLOADS,
        json={**upload_body(), "mime_type": "image/gif"},
        headers=headers,
    )
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "MEDIA_TYPE_UNSUPPORTED"


def test_an_oversized_declaration_is_refused_before_any_url_is_minted(
    client: TestClient,
) -> None:
    headers = {**auth_header(client), "Idempotency-Key": str(uuid4())}
    response = client.post(
        UPLOADS,
        json={**upload_body(), "byte_size": 900_000_000},
        headers=headers,
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "MEDIA_TOO_LARGE"


def test_an_unregistered_device_cannot_open_an_upload(client: TestClient) -> None:
    """Device ownership is settled before presence, and before any presigned URL."""
    headers = {**auth_header(client), "Idempotency-Key": str(uuid4())}
    response = client.post(UPLOADS, json=upload_body(), headers=headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DEVICE_NOT_FOUND"


# ----------------------------------------------------------------------- feed


def test_an_empty_venue_feed_is_a_well_formed_page(client: TestClient) -> None:
    response = client.get(f"/v1/venues/{uuid4()}/vibes", headers=auth_header(client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data"] == {"items": [], "next_cursor": None}
    assert body["meta"]["request_id"]


def test_the_page_size_is_capped(client: TestClient) -> None:
    headers = auth_header(client)
    response = client.get(f"/v1/venues/{uuid4()}/vibes", params={"limit": 500}, headers=headers)
    assert response.status_code == 422


def test_a_forged_cursor_is_rejected(client: TestClient) -> None:
    response = client.get(
        f"/v1/venues/{uuid4()}/vibes",
        params={"cursor": "eyJhIjoxfQ.forged"},
        headers=auth_header(client),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CURSOR_INVALID"


# -------------------------------------------------------------- reports/delete


def test_reporting_an_unknown_vibe_is_a_not_found(client: TestClient) -> None:
    response = client.post(
        f"/v1/vibes/{uuid4()}/reports",
        json={"reason": "harassment"},
        headers=auth_header(client),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VIBE_NOT_FOUND"


def test_an_unknown_report_reason_is_rejected(client: TestClient) -> None:
    response = client.post(
        f"/v1/vibes/{uuid4()}/reports",
        json={"reason": "i-just-dont-like-it"},
        headers=auth_header(client),
    )
    assert response.status_code == 422


def test_deleting_an_unknown_vibe_is_a_not_found(client: TestClient) -> None:
    response = client.delete(f"/v1/vibes/{uuid4()}", headers=auth_header(client))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "VIBE_NOT_FOUND"


def test_an_unknown_upload_is_a_not_found(client: TestClient) -> None:
    response = client.get(f"{UPLOADS}/{uuid4()}", headers=auth_header(client))
    assert response.status_code == 404
