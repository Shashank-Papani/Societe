from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.modules.presence.engine import PresenceEngine, compute_purge_at
from app.modules.presence.geospatial import VenueCandidate
from app.modules.presence.leases import LeaseWrite, PresenceLeaseStore
from app.modules.presence.samples import PresenceSample
from app.modules.presence.schemas import EvidenceRequest

VENUE_A = UUID("11111111-1111-1111-1111-111111111111")
VENUE_B = UUID("22222222-2222-2222-2222-222222222222")


def make_candidate(
    venue_id: UUID,
    *,
    inside: bool,
    boundary_distance_m: float,
    entry_buffer_m: float = 10.0,
    exit_buffer_m: float = 25.0,
    max_gps_accuracy_m: float = 50.0,
    entry_dwell_seconds: int = 10,
    exit_dwell_seconds: int = 30,
    centroid_distance_m: float | None = None,
) -> VenueCandidate:
    return VenueCandidate(
        id=venue_id,
        name=f"Venue {venue_id}",
        timezone="America/Los_Angeles",
        geofence_version=1,
        max_gps_accuracy_m=max_gps_accuracy_m,
        entry_dwell_seconds=entry_dwell_seconds,
        exit_dwell_seconds=exit_dwell_seconds,
        entry_buffer_m=entry_buffer_m,
        exit_buffer_m=exit_buffer_m,
        inside=inside,
        boundary_distance_m=boundary_distance_m,
        # Default far from centroid so polygon-buffer tests are not short-circuited
        # by the product entry-radius (160.9344 m) path.
        centroid_distance_m=(
            centroid_distance_m
            if centroid_distance_m is not None
            else max(boundary_distance_m + 20.0, 500.0)
        ),
        polygon_area_m2=500.0,
    )


def make_sample(
    *,
    venue_id: UUID | None,
    verdict: str,
    received_at: datetime,
    credible_outside: bool = False,
) -> PresenceSample:
    return PresenceSample(
        server_received_at=received_at,
        observed_at=received_at,
        client_sequence=1,
        venue_id=str(venue_id) if venue_id else None,
        verdict=verdict,  # type: ignore[arg-type]
        accuracy_m=8.0,
        boundary_distance_m=0.0,
        geofence_version=1,
        credible_outside=credible_outside,
    )


class FakeScript:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], list[str]]] = []

    async def __call__(self, *, keys: list[str], args: list[str]) -> list[str]:
        self.calls.append((keys, args))
        return ["", ""]


class FakeRedis:
    def __init__(self) -> None:
        self.script = FakeScript()

    def register_script(self, _source: str) -> FakeScript:
        return self.script


def make_engine() -> tuple[PresenceEngine, FakeRedis]:
    redis = FakeRedis()
    settings = Settings(auth_provider="cognito")
    engine = PresenceEngine(None, redis, settings)  # type: ignore[arg-type]
    return engine, redis


# --------------------------------------------------------------- config gates


def test_location_simulator_flag_rejected_in_production() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(app_env="production", auth_provider="cognito", ff_location_simulator=True)
    assert "FF_LOCATION_SIMULATOR" in str(exc.value)


def test_location_simulator_flag_rejected_in_staging() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(app_env="staging", auth_provider="cognito", ff_location_simulator=True)
    assert "FF_LOCATION_SIMULATOR" in str(exc.value)


def test_location_simulator_flag_allowed_in_development() -> None:
    settings = Settings(app_env="development", ff_location_simulator=True)
    assert settings.ff_location_simulator is True


def test_invalid_default_purge_timezone_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(auth_provider="cognito", default_purge_timezone="Mars/Olympus_Mons")
    assert "DEFAULT_PURGE_TIMEZONE" in str(exc.value)


# ------------------------------------------------------------------- schemas


def _evidence_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "evidence_id": str(uuid4()),
        "observed_at": "2026-07-24T02:15:20.123Z",
        "location": {
            "latitude": 34.098,
            "longitude": -118.329,
            "horizontal_accuracy_m": 12.4,
            "provider": "fused",
        },
        "platform_signals": {
            "is_mock": False,
            "is_simulated": False,
            "app_state": "foreground",
        },
        "client_sequence": 1042,
        "device_id": str(uuid4()),
    }
    payload.update(overrides)
    return payload


def test_evidence_request_accepts_fused_location_only() -> None:
    request = EvidenceRequest.model_validate(_evidence_payload())
    assert request.location.provider == "fused"


@pytest.mark.parametrize(
    "proof_field",
    ["wifi_proof", "ble_proof", "qr_proof", "attestation"],
)
def test_evidence_request_rejects_proof_envelopes(proof_field: str) -> None:
    """Phase 5 proofs must fail loudly rather than be silently ignored."""
    with pytest.raises(ValidationError):
        EvidenceRequest.model_validate(_evidence_payload(**{proof_field: {"token": "x"}}))


def test_evidence_request_rejects_naive_observed_at() -> None:
    with pytest.raises(ValidationError):
        EvidenceRequest.model_validate(_evidence_payload(observed_at="2026-07-24T02:15:20"))


# --------------------------------------------------------------- purge window


def test_purge_at_is_next_six_am_in_venue_timezone() -> None:
    settings = Settings(auth_provider="cognito")
    # 02:00 local in Los Angeles on a July night (UTC-7).
    received_at = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
    purge_at = compute_purge_at(received_at, "America/Los_Angeles", settings)
    assert purge_at == datetime(2026, 7, 24, 13, 0, tzinfo=UTC)


def test_purge_at_rolls_to_next_day_after_six_am() -> None:
    settings = Settings(auth_provider="cognito")
    # 08:00 local, already past the 06:00 boundary.
    received_at = datetime(2026, 7, 24, 15, 0, tzinfo=UTC)
    purge_at = compute_purge_at(received_at, "America/Los_Angeles", settings)
    assert purge_at == datetime(2026, 7, 25, 13, 0, tzinfo=UTC)


def test_purge_at_capped_by_absolute_retention() -> None:
    settings = Settings(auth_provider="cognito", evidence_absolute_max_retention_hours=2)
    received_at = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
    purge_at = compute_purge_at(received_at, "America/Los_Angeles", settings)
    assert purge_at == received_at + timedelta(hours=2)


def test_unknown_venue_timezone_falls_back_to_default() -> None:
    settings = Settings(auth_provider="cognito")
    received_at = datetime(2026, 7, 24, 9, 0, tzinfo=UTC)
    assert compute_purge_at(received_at, "Mars/Olympus_Mons", settings) == compute_purge_at(
        received_at, settings.default_purge_timezone, settings
    )


# ------------------------------------------------------------------ ambiguity


def test_two_covering_polygons_are_ambiguous() -> None:
    engine, _ = make_engine()
    candidates = [
        make_candidate(VENUE_A, inside=True, boundary_distance_m=0.0),
        make_candidate(VENUE_B, inside=True, boundary_distance_m=0.0),
    ]
    ambiguous, reasons = engine._detect_ambiguity(candidates, 8.0)
    assert ambiguous
    assert reasons == ["multiple_polygons_cover_point"]


def test_neighbor_inside_accuracy_radius_is_ambiguous() -> None:
    engine, _ = make_engine()
    candidates = [
        make_candidate(VENUE_A, inside=True, boundary_distance_m=0.0),
        make_candidate(VENUE_B, inside=False, boundary_distance_m=14.0),
    ]
    ambiguous, reasons = engine._detect_ambiguity(candidates, 20.0)
    assert ambiguous
    assert reasons == ["neighbor_within_accuracy_radius"]


def test_touching_neighbor_is_ambiguous_even_with_perfect_accuracy() -> None:
    engine, _ = make_engine()
    candidates = [
        make_candidate(VENUE_A, inside=True, boundary_distance_m=0.0),
        make_candidate(VENUE_B, inside=False, boundary_distance_m=0.0),
    ]
    ambiguous, reasons = engine._detect_ambiguity(candidates, 0.0)
    assert ambiguous
    assert reasons == ["shared_boundary_with_neighbor"]


def test_distant_neighbor_is_not_ambiguous() -> None:
    engine, _ = make_engine()
    candidates = [
        make_candidate(VENUE_A, inside=True, boundary_distance_m=0.0),
        make_candidate(VENUE_B, inside=False, boundary_distance_m=90.0),
    ]
    ambiguous, reasons = engine._detect_ambiguity(candidates, 10.0)
    assert not ambiguous
    assert reasons == []


# ------------------------------------------------------------ venue selection


def test_covering_venue_wins_over_buffer_candidate() -> None:
    engine, _ = make_engine()
    candidates = [
        make_candidate(VENUE_A, inside=True, boundary_distance_m=0.0),
        make_candidate(VENUE_B, inside=False, boundary_distance_m=5.0),
    ]
    selected, inside = engine._select_candidate(candidates, accuracy_m=8.0, hint=None)
    assert selected is not None
    assert selected.id == VENUE_A
    assert inside is True


def test_entry_buffer_widens_with_accuracy_but_is_capped() -> None:
    engine, _ = make_engine()
    # entry_buffer 10 + min(accuracy, max_gps_accuracy 50) = at most 60 m.
    # Keep centroid far so product entry-radius hysteresis does not apply.
    near = make_candidate(
        VENUE_A, inside=False, boundary_distance_m=55.0, centroid_distance_m=500.0
    )
    far = make_candidate(VENUE_B, inside=False, boundary_distance_m=65.0, centroid_distance_m=500.0)

    selected, inside = engine._select_candidate([near], accuracy_m=500.0, hint=None)
    assert selected is not None and selected.id == VENUE_A
    assert inside is False

    assert engine._select_candidate([far], accuracy_m=500.0, hint=None) == (None, False)


def test_centroid_within_entry_radius_counts_as_inside() -> None:
    engine, _ = make_engine()
    candidate = make_candidate(
        VENUE_A,
        inside=False,
        boundary_distance_m=200.0,
        centroid_distance_m=100.0,
    )
    selected, inside = engine._select_candidate([candidate], accuracy_m=8.0, hint=None)
    assert selected is not None
    assert inside is True


def test_candidate_hint_only_breaks_ties_inside_the_buffer() -> None:
    engine, _ = make_engine()
    candidates = [
        make_candidate(VENUE_A, inside=False, boundary_distance_m=3.0),
        make_candidate(VENUE_B, inside=False, boundary_distance_m=6.0),
    ]
    selected, _ = engine._select_candidate(candidates, accuracy_m=8.0, hint=VENUE_B)
    assert selected is not None
    assert selected.id == VENUE_B


# ------------------------------------------------------------------ hysteresis


def test_entry_dwell_needs_a_prior_sample_spaced_by_the_dwell_window() -> None:
    engine, _ = make_engine()
    now = datetime(2026, 7, 24, 3, 0, tzinfo=UTC)

    assert not engine._dwell_satisfied(
        [], venue_id=VENUE_A, received_at=now, dwell_seconds=10, verdict="inside"
    )

    too_soon = [
        make_sample(venue_id=VENUE_A, verdict="inside", received_at=now - timedelta(seconds=4))
    ]
    assert not engine._dwell_satisfied(
        too_soon, venue_id=VENUE_A, received_at=now, dwell_seconds=10, verdict="inside"
    )

    spaced = [
        make_sample(venue_id=VENUE_A, verdict="inside", received_at=now - timedelta(seconds=11))
    ]
    assert engine._dwell_satisfied(
        spaced, venue_id=VENUE_A, received_at=now, dwell_seconds=10, verdict="inside"
    )


def test_provisional_samples_do_not_count_toward_entry_dwell() -> None:
    engine, _ = make_engine()
    now = datetime(2026, 7, 24, 3, 0, tzinfo=UTC)
    weak = [
        make_sample(
            venue_id=VENUE_A, verdict="provisional_buffer", received_at=now - timedelta(seconds=60)
        )
    ]
    assert not engine._dwell_satisfied(
        weak, venue_id=VENUE_A, received_at=now, dwell_seconds=10, verdict="inside"
    )


def test_exit_needs_two_credible_outside_samples_spaced_by_exit_dwell() -> None:
    engine, _ = make_engine()
    now = datetime(2026, 7, 24, 3, 0, tzinfo=UTC)

    assert not engine._exit_dwell_satisfied(
        [], venue_id=VENUE_A, received_at=now, exit_dwell_seconds=30
    )

    recent = [
        make_sample(
            venue_id=VENUE_A,
            verdict="outside",
            received_at=now - timedelta(seconds=10),
            credible_outside=True,
        )
    ]
    assert not engine._exit_dwell_satisfied(
        recent, venue_id=VENUE_A, received_at=now, exit_dwell_seconds=30
    )

    spaced = [
        make_sample(
            venue_id=VENUE_A,
            verdict="outside",
            received_at=now - timedelta(seconds=31),
            credible_outside=True,
        )
    ]
    assert engine._exit_dwell_satisfied(
        spaced, venue_id=VENUE_A, received_at=now, exit_dwell_seconds=30
    )


def test_uncertain_outside_samples_never_trigger_exit() -> None:
    engine, _ = make_engine()
    now = datetime(2026, 7, 24, 3, 0, tzinfo=UTC)
    uncertain = [
        make_sample(
            venue_id=VENUE_A,
            verdict="outside",
            received_at=now - timedelta(minutes=5),
            credible_outside=False,
        )
    ]
    assert not engine._exit_dwell_satisfied(
        uncertain, venue_id=VENUE_A, received_at=now, exit_dwell_seconds=30
    )


# ---------------------------------------------------------------- lease write


async def _write_lease(**overrides: Any) -> tuple[list[str], list[str]]:
    redis = FakeRedis()
    store = PresenceLeaseStore(redis)  # type: ignore[arg-type]
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "user_id": uuid4(),
        "venue_id": VENUE_A,
        "check_in_id": uuid4(),
        "state": "verified",
        "confidence": 90,
        "verification_level": "standard",
        "ghost_mode": False,
        "discoverable": True,
        "verified_until": now + timedelta(seconds=120),
        "grace_until": now + timedelta(seconds=420),
        "lease_version": 1,
    }
    payload.update(overrides)
    await store.update(LeaseWrite(**payload))
    return redis.script.calls[0]


async def test_lease_write_passes_old_and_new_venue_keys() -> None:
    keys, _ = await _write_lease(previous_venue_id=VENUE_B)
    assert keys[1] == f"presence:venue:{VENUE_A}:active"
    assert keys[3] == f"presence:venue:{VENUE_B}:active"
    assert keys[5] == "presence:lease_expirations"


async def test_lease_write_reuses_new_keys_when_venue_is_unchanged() -> None:
    keys, _ = await _write_lease()
    assert keys[1] == keys[3]
    assert keys[2] == keys[4]


async def test_verified_lease_schedules_next_transition_at_verified_until() -> None:
    _, args = await _write_lease()
    verified_until, grace_until, next_transition = args[7], args[8], args[12]
    assert next_transition == verified_until
    assert next_transition != grace_until


async def test_degraded_lease_schedules_next_transition_at_grace_until() -> None:
    _, args = await _write_lease(state="degraded")
    assert args[12] == args[8]
