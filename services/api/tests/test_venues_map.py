from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _cursor_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CURSOR_HMAC_SECRET", "test-cursor-hmac-secret-0123456789abcdef01234567")
    from app.core.config import get_settings

    get_settings.cache_clear()


def _auth_header(client: TestClient) -> dict[str, str]:
    token = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_age_bands_rejected(client: TestClient) -> None:
    headers = _auth_header(client)
    response = client.get(
        "/v1/map/venues",
        params={
            "latitude": 34.0955,
            "longitude": -118.344,
            "age_bands": "21-24",
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "FILTER_NOT_AVAILABLE"


def test_crowd_buckets_rejected(client: TestClient) -> None:
    headers = _auth_header(client)
    response = client.get(
        "/v1/map/venues",
        params={
            "latitude": 34.0955,
            "longitude": -118.344,
            "crowd_buckets": "busy",
        },
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "FILTER_NOT_AVAILABLE"


def test_map_venues_nearby_and_pagination(client: TestClient) -> None:
    headers = _auth_header(client)
    first = client.get(
        "/v1/map/venues",
        params={
            "latitude": 34.0955,
            "longitude": -118.344,
            "radius_m": 25000,
            "limit": 2,
        },
        headers=headers,
    )
    assert first.status_code == 200, first.text
    body = first.json()["data"]
    assert len(body["items"]) <= 2
    for item in body["items"]:
        assert "map_pin" in item
        assert "boundary_geojson" not in item
        assert "supports_qr_proof" not in item
        assert "geofence_version" not in item
        assert "max_gps_accuracy_m" not in item

    if body["next_cursor"]:
        second = client.get(
            "/v1/map/venues",
            params={
                "latitude": 34.0955,
                "longitude": -118.344,
                "radius_m": 25000,
                "limit": 2,
                "cursor": body["next_cursor"],
            },
            headers=headers,
        )
        assert second.status_code == 200
        ids_first = {item["id"] for item in body["items"]}
        ids_second = {item["id"] for item in second.json()["data"]["items"]}
        assert ids_first.isdisjoint(ids_second)

        # Cursor must not work with a different query fingerprint.
        mismatch = client.get(
            "/v1/map/venues",
            params={
                "latitude": 34.0955,
                "longitude": -118.344,
                "radius_m": 1000,
                "limit": 2,
                "cursor": body["next_cursor"],
            },
            headers=headers,
        )
        assert mismatch.status_code == 400
        assert mismatch.json()["error"]["code"] == "CURSOR_QUERY_MISMATCH"


def test_venue_detail_omits_security_fields(client: TestClient) -> None:
    headers = _auth_header(client)
    listing = client.get(
        "/v1/map/venues",
        params={"latitude": 34.0955, "longitude": -118.344, "radius_m": 25000, "limit": 1},
        headers=headers,
    )
    assert listing.status_code == 200
    items = listing.json()["data"]["items"]
    if not items:
        pytest.skip("Seed venues required")
    venue_id = items[0]["id"]
    detail = client.get(f"/v1/venues/{venue_id}", headers=headers)
    assert detail.status_code == 200
    data = detail.json()["data"]
    assert "hours" in data
    assert "centroid" in data
    for forbidden in (
        "boundary_geojson",
        "entrance_point",
        "geofence_version",
        "max_gps_accuracy_m",
        "entry_buffer_m",
        "exit_buffer_m",
        "supports_qr_proof",
        "supports_ble_proof",
        "supports_wifi_proof",
    ):
        assert forbidden not in data


def test_static_cache_hydration_keys(client: TestClient) -> None:
    from redis import Redis

    from app.core.config import get_settings

    headers = _auth_header(client)
    settings = get_settings()
    # Use sync client so we do not bind the async Redis singleton to a throwaway loop.
    sync_redis = Redis.from_url(settings.valkey_url, decode_responses=True)
    for key in sync_redis.scan_iter(match="venue:static:v1:*"):
        sync_redis.delete(key)
    sync_redis.close()

    first = client.get(
        "/v1/map/venues",
        params={"latitude": 34.0955, "longitude": -118.344, "radius_m": 25000, "limit": 5},
        headers=headers,
    )
    assert first.status_code == 200
    second = client.get(
        "/v1/map/venues",
        params={"latitude": 34.0955, "longitude": -118.344, "radius_m": 25000, "limit": 5},
        headers=headers,
    )
    assert second.status_code == 200
    assert len(second.json()["data"]["items"]) == len(first.json()["data"]["items"])
