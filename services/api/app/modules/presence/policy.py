"""Centralized presence retention policy.

Radii and timers are server-authoritative. Clients submit location evidence;
they never decide eligibility, lease expiry, or outside confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.db.models import Venue

# Exact product defaults (meters / seconds). Keep as module constants for tests.
ENTRY_RADIUS_METERS = 160.9344
RETENTION_RADIUS_METERS = 241.4016
PRESENCE_LEASE_SECONDS = 1800
PRESENCE_GRACE_SECONDS = 900
MAX_WITHOUT_EVIDENCE_SECONDS = 2700
OUTSIDE_CONFIRMATIONS_REQUIRED = 2
OUTSIDE_CONFIRMATION_DELAY_SECONDS = 90
FOREGROUND_HEARTBEAT_SECONDS = 180
MOVEMENT_TRIGGER_METERS = 30
BACKGROUND_HEARTBEAT_SECONDS = 600
BACKGROUND_DISTANCE_INTERVAL_METERS = 50


@dataclass(frozen=True)
class PresencePolicy:
    entry_radius_meters: float
    retention_radius_meters: float
    lease_seconds: int
    grace_seconds: int
    outside_confirmations_required: int
    outside_confirmation_delay_seconds: int
    max_evidence_age_seconds: int
    maximum_location_accuracy_meters: float
    max_without_evidence_seconds: int

    @property
    def max_without_evidence(self) -> int:
        return self.lease_seconds + self.grace_seconds


def policy_from_settings(settings: Settings) -> PresencePolicy:
    return PresencePolicy(
        entry_radius_meters=settings.presence_entry_radius_meters,
        retention_radius_meters=settings.presence_retention_radius_meters,
        lease_seconds=settings.verified_lease_seconds,
        grace_seconds=settings.degraded_grace_seconds,
        outside_confirmations_required=settings.presence_outside_confirmations_required,
        outside_confirmation_delay_seconds=settings.presence_outside_confirmation_delay_seconds,
        max_evidence_age_seconds=settings.max_evidence_age_seconds,
        maximum_location_accuracy_meters=float(settings.presence_default_max_accuracy_meters),
        max_without_evidence_seconds=(
            settings.verified_lease_seconds + settings.degraded_grace_seconds
        ),
    )


def resolve_venue_policy(settings: Settings, venue: Venue | None) -> PresencePolicy:
    """Global policy with optional per-venue radius overrides."""
    base = policy_from_settings(settings)
    if venue is None:
        return base
    entry = getattr(venue, "entry_radius_m", None)
    retention = getattr(venue, "retention_radius_m", None)
    accuracy = venue.max_gps_accuracy_m
    return PresencePolicy(
        entry_radius_meters=float(entry) if entry is not None else base.entry_radius_meters,
        retention_radius_meters=(
            float(retention) if retention is not None else base.retention_radius_meters
        ),
        lease_seconds=base.lease_seconds,
        grace_seconds=base.grace_seconds,
        outside_confirmations_required=base.outside_confirmations_required,
        outside_confirmation_delay_seconds=base.outside_confirmation_delay_seconds,
        max_evidence_age_seconds=base.max_evidence_age_seconds,
        maximum_location_accuracy_meters=float(accuracy)
        if accuracy is not None
        else base.maximum_location_accuracy_meters,
        max_without_evidence_seconds=base.max_without_evidence_seconds,
    )


def within_entry_radius(*, distance_meters: float, policy: PresencePolicy) -> bool:
    return distance_meters <= policy.entry_radius_meters


def within_retention_radius(*, distance_meters: float, policy: PresencePolicy) -> bool:
    return distance_meters <= policy.retention_radius_meters
