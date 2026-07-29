"""Read-only presence eligibility preview — no lease/evidence writes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


def _auth_header(client: TestClient) -> dict[str, str]:
    token = client.post("/v1/auth/local/token", json={}).json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    # Best-effort clear of leftover presence from heartbeat integration tests.
    client.post(
        "/v1/presence/leave",
        headers={**headers, "Idempotency-Key": str(uuid4())},
        json={"confirmation": "LEAVE"},
    )
    return headers


def _neon_house_id(client: TestClient, headers: dict[str, str]) -> str | None:
    response = client.get(
        "/v1/map/venues",
        params={
            "latitude": 34.0955,
            "longitude": -118.344,
            "radius_m": 25000,
            "limit": 10,
        },
        headers=headers,
    )
    if response.status_code != 200:
        return None
    for item in response.json()["data"]["items"]:
        if item.get("slug") == "societe-neon-house" or "Neon" in item.get("name", ""):
            return str(item["id"])
    items = response.json()["data"]["items"]
    return str(items[0]["id"]) if items else None


def test_eligibility_inside_is_eligible(client: TestClient) -> None:
    headers = _auth_header(client)
    venue_id = _neon_house_id(client, headers)
    if venue_id is None:
        return
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    response = client.post(
        "/v1/presence/eligibility",
        headers=headers,
        json={
            "latitude": 34.0955,
            "longitude": -118.3440,
            "horizontal_accuracy_m": 8.0,
            "observed_at": now,
            "candidate_venue_id": venue_id,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["eligible"] is True
    assert data["reason"] == "eligible"
    assert data["distance_meters"] == 0.0
    assert data["allowed_radius_meters"] is not None
    assert data["location_accuracy_meters"] == 8.0


def test_eligibility_too_far(client: TestClient) -> None:
    headers = _auth_header(client)
    venue_id = _neon_house_id(client, headers)
    if venue_id is None:
        return
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    response = client.post(
        "/v1/presence/eligibility",
        headers=headers,
        json={
            "latitude": 34.2,
            "longitude": -118.5,
            "horizontal_accuracy_m": 8.0,
            "observed_at": now,
            "candidate_venue_id": venue_id,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["eligible"] is False
    assert data["reason"] == "outside"
    assert data["distance_meters"] is not None
    assert data["distance_meters"] > 100


def test_eligibility_stale_location(client: TestClient) -> None:
    headers = _auth_header(client)
    venue_id = _neon_house_id(client, headers)
    if venue_id is None:
        return
    stale = (datetime.now(UTC) - timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    response = client.post(
        "/v1/presence/eligibility",
        headers=headers,
        json={
            "latitude": 34.0955,
            "longitude": -118.3440,
            "horizontal_accuracy_m": 8.0,
            "observed_at": stale,
            "candidate_venue_id": venue_id,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["eligible"] is False
    assert data["reason"] == "stale_evidence"
    assert data["distance_meters"] is None


def test_eligibility_low_accuracy(client: TestClient) -> None:
    headers = _auth_header(client)
    venue_id = _neon_house_id(client, headers)
    if venue_id is None:
        return
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    response = client.post(
        "/v1/presence/eligibility",
        headers=headers,
        json={
            "latitude": 34.0955,
            "longitude": -118.3440,
            "horizontal_accuracy_m": 500.0,
            "observed_at": now,
            "candidate_venue_id": venue_id,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["eligible"] is False
    assert data["reason"] == "accuracy_exceeds_venue_maximum"


def test_eligibility_uses_entry_radius_not_retention(client: TestClient) -> None:
    """~200 m is inside retention (0.15 mi) but outside entry (0.10 mi)."""
    headers = _auth_header(client)
    venue_id = _neon_house_id(client, headers)
    if venue_id is None:
        return
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    # ~200 m south of Neon House centroid (34.0955, -118.3440)
    response = client.post(
        "/v1/presence/eligibility",
        headers=headers,
        json={
            "latitude": 34.093703,
            "longitude": -118.3440,
            "horizontal_accuracy_m": 8.0,
            "observed_at": now,
            "candidate_venue_id": venue_id,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["eligible"] is False
    assert data["reason"] == "outside"
    assert data["allowed_radius_meters"] == pytest.approx(160.9344)
    assert data["distance_meters"] is not None
    assert data["distance_meters"] > 160.9344
    assert data["distance_meters"] < 241.4016


def test_eligibility_inside_entry_radius(client: TestClient) -> None:
    headers = _auth_header(client)
    venue_id = _neon_house_id(client, headers)
    if venue_id is None:
        return
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    # ~30 m south of Neon House centroid
    response = client.post(
        "/v1/presence/eligibility",
        headers=headers,
        json={
            "latitude": 34.09523,
            "longitude": -118.3440,
            "horizontal_accuracy_m": 8.0,
            "observed_at": now,
            "candidate_venue_id": venue_id,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["eligible"] is True
    assert data["allowed_radius_meters"] == pytest.approx(160.9344)


def test_eligibility_unknown_venue(client: TestClient) -> None:
    headers = _auth_header(client)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    response = client.post(
        "/v1/presence/eligibility",
        headers=headers,
        json={
            "latitude": 34.0955,
            "longitude": -118.3440,
            "horizontal_accuracy_m": 8.0,
            "observed_at": now,
            "candidate_venue_id": str(uuid4()),
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["eligible"] is False
    assert data["reason"] == "venue_not_found"
