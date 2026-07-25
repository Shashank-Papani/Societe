"""State machine and publication window.

The interesting cases are the illegal transitions. Anything that could turn an
unmoderated or already-deleted asset back into a publishable one has to raise,
because the alternative is a silent overwrite that nobody notices until the
media is public.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.db.models import LiveVibe, MediaAsset
from app.modules.media.lifecycle import (
    MediaLifecycleService,
    MediaStateError,
    VibeLifecycleService,
    compute_vibe_expiry,
)

NOW = datetime(2026, 7, 24, 4, 30, tzinfo=UTC)


def make_asset(status: str = "intent_pending", **overrides: Any) -> MediaAsset:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "owner_user_id": uuid4(),
        "venue_id": uuid4(),
        "author_check_in_id": uuid4(),
        "device_id": uuid4(),
        "media_type": "image",
        "lifecycle_status": status,
        "moderation_status": "pending",
        "attribution_mode": "attributed",
        "quarantine_object_key": "quarantine/u1/a1/original.jpg",
        "declared_mime_type": "image/jpeg",
        "declared_byte_size": 2048,
        "vibe_tags": [],
        "intent_expires_at": NOW + timedelta(minutes=15),
        "generation": 1,
        "moderation_summary": {},
        "created_at": NOW,
    }
    fields.update(overrides)
    return MediaAsset(**fields)


def make_vibe(status: str = "draft", **overrides: Any) -> LiveVibe:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "venue_id": uuid4(),
        "author_user_id": uuid4(),
        "media_asset_id": uuid4(),
        "author_check_in_id": uuid4(),
        "vibe_tags": [],
        "attribution_mode": "attributed",
        "publication_status": status,
        "created_at": NOW,
    }
    fields.update(overrides)
    return LiveVibe(**fields)


# ----------------------------------------------------------------- media asset


def test_accepted_upload_records_consumption_of_the_intent() -> None:
    """The intent is single-use: consuming it is part of the same transition."""
    asset = make_asset()
    MediaLifecycleService().mark_uploaded(asset, now=NOW)
    assert asset.lifecycle_status == "uploaded"
    assert asset.uploaded_at == NOW
    assert asset.intent_consumed_at == NOW


def test_happy_path_walks_intent_to_ready() -> None:
    media = MediaLifecycleService()
    asset = make_asset()
    media.mark_uploaded(asset, now=NOW)
    media.start_validation(asset, now=NOW)
    media.start_processing(asset, now=NOW)
    media.await_moderation(asset, now=NOW)
    media.mark_ready(asset, now=NOW, summary={"moderation_provider": "fake"})
    assert asset.lifecycle_status == "ready"
    assert asset.moderation_status == "approved"
    assert asset.processed_at == NOW


@pytest.mark.parametrize(
    ("start", "attempt"),
    [
        ("intent_pending", "ready"),
        ("uploaded", "ready"),
        ("processing", "ready"),
        ("rejected", "ready"),
        ("upload_expired", "uploaded"),
        ("deleted", "ready"),
        ("deleted", "validating"),
        ("invalid", "processing"),
    ],
)
def test_illegal_media_transitions_raise(start: str, attempt: str) -> None:
    media = MediaLifecycleService()
    asset = make_asset(start)
    method = {
        "ready": lambda: media.mark_ready(asset, now=NOW, summary={}),
        "uploaded": lambda: media.mark_uploaded(asset, now=NOW),
        "validating": lambda: media.start_validation(asset, now=NOW),
        "processing": lambda: media.start_processing(asset, now=NOW),
    }[attempt]
    with pytest.raises(MediaStateError) as exc:
        method()
    assert exc.value.status_code == 409
    assert asset.lifecycle_status == start


def test_repeating_the_current_state_is_a_no_op_not_an_error() -> None:
    """Retried workers replay transitions; that must not be a failure."""
    asset = make_asset("uploaded")
    MediaLifecycleService().mark_uploaded(asset, now=NOW + timedelta(minutes=1))
    assert asset.lifecycle_status == "uploaded"


def test_unknown_status_is_refused_rather_than_guessed() -> None:
    asset = make_asset("something_new")
    with pytest.raises(MediaStateError):
        MediaLifecycleService().start_validation(asset, now=NOW)


def test_failed_processing_may_be_retried_from_the_original() -> None:
    media = MediaLifecycleService()
    asset = make_asset("processing")
    media.mark_processing_failed(asset, now=NOW, error_category="download")
    assert asset.lifecycle_status == "processing_failed"
    media.start_validation(asset, now=NOW)
    assert asset.lifecycle_status == "validating"


def test_quarantine_never_lands_in_a_publishable_state() -> None:
    asset = make_asset("validating")
    MediaLifecycleService().mark_quarantined(asset, now=NOW, summary={"malware_provider": "noop"})
    assert asset.lifecycle_status == "manual_review"
    assert asset.moderation_status == "quarantined"


def test_summary_is_replaced_so_sqlalchemy_sees_the_change() -> None:
    """In-place JSONB edits are invisible without a mutable type."""
    asset = make_asset("uploaded", moderation_summary={"declared_checksum_sha256": "a" * 64})
    before = asset.moderation_summary
    MediaLifecycleService().start_validation(asset, now=NOW)
    assert asset.moderation_summary is not before
    assert asset.moderation_summary["declared_checksum_sha256"] == "a" * 64
    assert "validation_started_at" in asset.moderation_summary


# ------------------------------------------------------------------ live vibes


def test_publication_stamps_the_window_and_clears_any_hidden_marker() -> None:
    settings = Settings(auth_provider="cognito")
    vibes = VibeLifecycleService(settings)
    vibe = make_vibe("processing")
    expires_at = vibes.publish(vibe, now=NOW, venue_timezone="America/Los_Angeles")
    assert vibe.publication_status == "published"
    assert vibe.published_at == NOW
    assert vibe.expires_at == expires_at
    assert vibe.hidden_at is None


def test_a_draft_can_never_be_published_directly() -> None:
    """Publication requires having gone through processing and moderation."""
    vibes = VibeLifecycleService(Settings(auth_provider="cognito"))
    with pytest.raises(MediaStateError):
        vibes.publish(make_vibe("draft"), now=NOW, venue_timezone="America/Los_Angeles")


@pytest.mark.parametrize("start", ["expired", "removed", "rejected", "deleted"])
def test_closed_vibes_cannot_be_republished(start: str) -> None:
    vibes = VibeLifecycleService(Settings(auth_provider="cognito"))
    with pytest.raises(MediaStateError):
        vibes.unhide(make_vibe(start), now=NOW)


def test_hidden_content_can_be_restored_after_review() -> None:
    vibes = VibeLifecycleService(Settings(auth_provider="cognito"))
    vibe = make_vibe("published", published_at=NOW)
    vibes.hide(vibe, now=NOW, reason="report_threshold")
    assert vibe.hidden_reason == "report_threshold"
    vibes.unhide(vibe, now=NOW)
    assert vibe.publication_status == "published"
    assert vibe.hidden_reason is None


def test_expiry_keeps_an_existing_window_and_fills_a_missing_one() -> None:
    vibes = VibeLifecycleService(Settings(auth_provider="cognito"))
    stamped = make_vibe("published", expires_at=NOW + timedelta(hours=1))
    vibes.expire(stamped, now=NOW)
    assert stamped.expires_at == NOW + timedelta(hours=1)

    draft = make_vibe("draft")
    vibes.expire(draft, now=NOW)
    assert draft.expires_at == NOW


# ------------------------------------------------------------- expiry window


def test_window_closes_at_the_next_local_six_am() -> None:
    settings = Settings(auth_provider="cognito")
    # 21:00 on 23 July in Los Angeles (UTC-7).
    published_at = datetime(2026, 7, 24, 4, 0, tzinfo=UTC)
    assert compute_vibe_expiry(published_at, "America/Los_Angeles", settings) == datetime(
        2026, 7, 24, 13, 0, tzinfo=UTC
    )


def test_publishing_just_before_the_boundary_still_closes_at_the_boundary() -> None:
    """A clip posted at 05:59 local disappears a minute later, by design."""
    settings = Settings(auth_provider="cognito")
    published_at = datetime(2026, 7, 24, 12, 59, tzinfo=UTC)  # 05:59 local
    assert compute_vibe_expiry(published_at, "America/Los_Angeles", settings) == datetime(
        2026, 7, 24, 13, 0, tzinfo=UTC
    )


def test_publishing_just_after_the_boundary_is_bounded_by_the_absolute_maximum() -> None:
    """A morning post would otherwise get a nearly 24-hour window.

    The next local 06:00 is almost a day away, so the absolute maximum lifetime
    is what actually closes the window.
    """
    settings = Settings(auth_provider="cognito")
    published_at = datetime(2026, 7, 24, 13, 1, tzinfo=UTC)  # 06:01 local
    assert compute_vibe_expiry(
        published_at, "America/Los_Angeles", settings
    ) == published_at + timedelta(hours=settings.vibe_absolute_max_lifetime_hours)


def test_the_local_boundary_wins_for_a_late_night_post() -> None:
    settings = Settings(auth_provider="cognito")
    published_at = datetime(2026, 7, 24, 8, 0, tzinfo=UTC)  # 01:00 local
    boundary = datetime(2026, 7, 24, 13, 0, tzinfo=UTC)  # 06:00 local, 5 hours later
    assert compute_vibe_expiry(published_at, "America/Los_Angeles", settings) == boundary
    assert boundary < published_at + timedelta(hours=settings.vibe_absolute_max_lifetime_hours)


def test_absolute_maximum_lifetime_caps_the_local_boundary() -> None:
    settings = Settings(auth_provider="cognito", vibe_absolute_max_lifetime_hours=2)
    published_at = datetime(2026, 7, 24, 4, 0, tzinfo=UTC)
    assert compute_vibe_expiry(
        published_at, "America/Los_Angeles", settings
    ) == published_at + timedelta(hours=2)


def test_expiry_is_measured_from_publication_not_from_intent_creation() -> None:
    """Time spent in moderation must not eat into the public window."""
    settings = Settings(auth_provider="cognito")
    intent_created = datetime(2026, 7, 24, 4, 0, tzinfo=UTC)
    published_late = intent_created + timedelta(minutes=45)
    assert compute_vibe_expiry(
        published_late, "America/Los_Angeles", settings
    ) == compute_vibe_expiry(intent_created, "America/Los_Angeles", settings)


def test_unknown_venue_timezone_falls_back_to_the_configured_default() -> None:
    settings = Settings(auth_provider="cognito")
    published_at = datetime(2026, 7, 24, 4, 0, tzinfo=UTC)
    assert compute_vibe_expiry(published_at, "Mars/Olympus_Mons", settings) == compute_vibe_expiry(
        published_at, settings.default_purge_timezone, settings
    )


def test_configured_closing_hour_is_respected() -> None:
    settings = Settings(auth_provider="cognito", vibe_expiry_local_hour=4)
    published_at = datetime(2026, 7, 24, 4, 0, tzinfo=UTC)  # 21:00 local
    assert compute_vibe_expiry(published_at, "America/Los_Angeles", settings) == datetime(
        2026, 7, 24, 11, 0, tzinfo=UTC
    )
