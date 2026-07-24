"""Presence wire contracts.

Phase 2 accepts fused-location evidence only. Wi-Fi, BLE, QR, and attestation
proof envelopes are deliberately absent: ``extra="forbid"`` makes a client that
sends them fail loudly instead of having a proof silently ignored while the
response still says ``verified``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

PresenceState = Literal[
    "outside",
    "refresh_required",
    "provisional",
    "verified",
    "degraded",
    "exited",
    "ambiguous",
    "rejected",
]

VerificationLevel = Literal["weak", "standard"]

LocationProvider = Literal["fused", "gps", "network", "simulated"]

AppState = Literal["foreground", "background"]

SampleVerdict = Literal["inside", "outside", "ambiguous", "provisional_buffer"]


class EvidenceLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    horizontal_accuracy_m: float = Field(ge=0.0, le=10_000.0)
    altitude_m: float | None = Field(default=None, ge=-500.0, le=12_000.0)
    speed_mps: float | None = Field(default=None, ge=0.0, le=350.0)
    provider: LocationProvider


class PlatformSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_mock: bool
    is_simulated: bool
    app_state: AppState


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: UUID
    observed_at: AwareDatetime
    location: EvidenceLocation
    platform_signals: PlatformSignals
    candidate_venue_id: UUID | None = None
    client_sequence: int = Field(ge=0)
    device_id: UUID


class LeaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["LEAVE"] | None = None


class SimulatorRequest(BaseModel):
    """Development-only spatial input; replayed through the production engine."""

    model_config = ConfigDict(extra="forbid")

    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    horizontal_accuracy_m: float = Field(default=8.0, ge=0.0, le=10_000.0)
    altitude_m: float | None = Field(default=None, ge=-500.0, le=12_000.0)
    speed_mps: float | None = Field(default=None, ge=0.0, le=350.0)
    provider: LocationProvider = "simulated"
    candidate_venue_id: UUID | None = None
    client_sequence: int = Field(default=0, ge=0)
    device_id: UUID


class PresenceVenue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str


class PresenceData(BaseModel):
    """Client-visible presence. Never carries coordinates or fraud scores."""

    model_config = ConfigDict(extra="forbid")

    state: PresenceState
    venue: PresenceVenue | None = None
    verification_level: VerificationLevel | None = None
    lease_expires_at: datetime | None = None
    social_features_enabled: bool = False
    challenge: None = None
    decision: str
    reasons: list[str] = Field(default_factory=list)


class PresenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: PresenceData
