"""Presence retention: entry/retention hysteresis, lease, grace, outside confirmations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.presence.policy import (
    ENTRY_RADIUS_METERS,
    OUTSIDE_CONFIRMATION_DELAY_SECONDS,
    PRESENCE_GRACE_SECONDS,
    PRESENCE_LEASE_SECONDS,
    RETENTION_RADIUS_METERS,
    PresencePolicy,
    policy_from_settings,
    within_entry_radius,
    within_retention_radius,
)
from app.modules.presence.schemas import HeartbeatRequest, PresenceData


def test_policy_defaults_match_product_constants() -> None:
    settings = Settings(auth_provider="cognito")
    policy = policy_from_settings(settings)
    assert policy.entry_radius_meters == ENTRY_RADIUS_METERS
    assert policy.retention_radius_meters == RETENTION_RADIUS_METERS
    assert policy.lease_seconds == PRESENCE_LEASE_SECONDS
    assert policy.grace_seconds == PRESENCE_GRACE_SECONDS
    assert policy.max_without_evidence_seconds == PRESENCE_LEASE_SECONDS + PRESENCE_GRACE_SECONDS
    assert policy.outside_confirmation_delay_seconds == OUTSIDE_CONFIRMATION_DELAY_SECONDS


def test_grace_may_be_shorter_than_lease() -> None:
    settings = Settings(
        auth_provider="cognito",
        verified_lease_seconds=1800,
        degraded_grace_seconds=900,
    )
    assert settings.degraded_grace_seconds == 900


def test_retention_must_be_at_least_entry() -> None:
    with pytest.raises(ValidationError):
        Settings(
            auth_provider="cognito",
            presence_entry_radius_meters=200,
            presence_retention_radius_meters=100,
        )


def test_entry_hysteresis_boundaries() -> None:
    policy = PresencePolicy(
        entry_radius_meters=ENTRY_RADIUS_METERS,
        retention_radius_meters=RETENTION_RADIUS_METERS,
        lease_seconds=1800,
        grace_seconds=900,
        outside_confirmations_required=2,
        outside_confirmation_delay_seconds=90,
        max_evidence_age_seconds=15,
        maximum_location_accuracy_meters=50,
        max_without_evidence_seconds=2700,
    )
    assert within_entry_radius(distance_meters=ENTRY_RADIUS_METERS, policy=policy)
    assert not within_entry_radius(distance_meters=ENTRY_RADIUS_METERS + 0.01, policy=policy)
    assert within_retention_radius(distance_meters=200.0, policy=policy)
    assert within_retention_radius(distance_meters=RETENTION_RADIUS_METERS, policy=policy)
    assert not within_retention_radius(
        distance_meters=RETENTION_RADIUS_METERS + 0.01, policy=policy
    )


def test_heartbeat_request_rejects_claimed_distance() -> None:
    with pytest.raises(ValidationError):
        HeartbeatRequest.model_validate(
            {
                "evidence_id": str(uuid4()),
                "observed_at": "2026-07-25T12:00:00Z",
                "location": {
                    "latitude": 34.0955,
                    "longitude": -118.344,
                    "horizontal_accuracy_m": 8,
                    "provider": "fused",
                },
                "platform_signals": {
                    "is_mock": False,
                    "is_simulated": False,
                    "app_state": "foreground",
                },
                "client_sequence": 1,
                "device_id": str(uuid4()),
                "distance_meters": 10,
            }
        )


def test_presence_data_exposes_safe_heartbeat_fields() -> None:
    now = datetime.now(UTC)
    data = PresenceData(
        state="rechecking",
        venue=None,
        verification_level="standard",
        lease_expires_at=now + timedelta(minutes=30),
        grace_expires_at=now + timedelta(minutes=45),
        entry_radius_meters=ENTRY_RADIUS_METERS,
        retention_radius_meters=RETENTION_RADIUS_METERS,
        distance_meters=300.0,
        next_recommended_check_at=now + timedelta(seconds=90),
        outside_confirmation_pending=True,
        social_features_enabled=True,
        decision="rechecking_outside",
        reasons=["outside_retention_pending_confirmation"],
    )
    dumped = data.model_dump()
    assert dumped["outside_confirmation_pending"] is True
    assert dumped["entry_radius_meters"] == ENTRY_RADIUS_METERS
    assert "latitude" not in dumped


def test_openapi_includes_heartbeat(client) -> None:  # type: ignore[no-untyped-def]
    paths = client.get("/openapi.json").json()["paths"]
    assert "/v1/presence/heartbeat" in paths
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    assert "HeartbeatRequest" in schema
    props = schema["HeartbeatRequest"]["properties"]
    assert "distance_meters" not in props
    assert "eligible" not in props
