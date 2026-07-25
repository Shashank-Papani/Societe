"""Signed-URL issuance policy and creator retention visibility."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.config import Settings
from app.db.models import LiveVibe, MediaAsset
from app.modules.media.access import may_issue_signed_urls
from app.modules.media.transcode import LocalFfmpegTranscoder, MediaConvertTranscoder

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def settings(**overrides: object) -> Settings:
    return Settings(auth_provider="cognito", **overrides)  # type: ignore[arg-type]


def make_asset(**overrides: object) -> MediaAsset:
    fields = {
        "id": uuid4(),
        "owner_user_id": uuid4(),
        "venue_id": uuid4(),
        "author_check_in_id": uuid4(),
        "device_id": uuid4(),
        "media_type": "image",
        "lifecycle_status": "ready",
        "moderation_status": "approved",
        "attribution_mode": "attributed",
        "quarantine_object_key": "quarantine/x",
        "declared_mime_type": "image/jpeg",
        "declared_byte_size": 100,
        "intent_expires_at": NOW + timedelta(minutes=15),
        "generation": 1,
        "deleted_at": None,
    }
    fields.update(overrides)
    return MediaAsset(**fields)  # type: ignore[arg-type]


def make_vibe(**overrides: object) -> LiveVibe:
    fields = {
        "id": uuid4(),
        "venue_id": uuid4(),
        "author_user_id": uuid4(),
        "media_asset_id": uuid4(),
        "author_check_in_id": uuid4(),
        "attribution_mode": "attributed",
        "publication_status": "published",
        "published_at": NOW - timedelta(hours=1),
        "expires_at": NOW + timedelta(hours=6),
        "created_at": NOW - timedelta(hours=2),
    }
    fields.update(overrides)
    return LiveVibe(**fields)  # type: ignore[arg-type]


def test_published_ready_asset_gets_public_urls() -> None:
    assert may_issue_signed_urls(
        make_asset(), make_vibe(), now=NOW, settings=settings(), creator_view=False
    )


def test_revoked_content_gets_no_new_signed_url() -> None:
    assert not may_issue_signed_urls(
        make_asset(),
        make_vibe(publication_status="revoked"),
        now=NOW,
        settings=settings(),
        creator_view=True,
    )


def test_deleted_asset_gets_no_new_signed_url() -> None:
    assert not may_issue_signed_urls(
        make_asset(deleted_at=NOW),
        make_vibe(),
        now=NOW,
        settings=settings(),
        creator_view=True,
    )


def test_rejected_asset_gets_no_new_signed_url() -> None:
    assert not may_issue_signed_urls(
        make_asset(lifecycle_status="rejected", moderation_status="rejected"),
        make_vibe(publication_status="rejected"),
        now=NOW,
        settings=settings(),
        creator_view=False,
    )


def test_expired_vibe_is_hidden_from_public_urls_but_visible_to_creator_in_retention() -> None:
    vibe = make_vibe(publication_status="expired", expires_at=NOW - timedelta(hours=1))
    cfg = settings(retention_processed_derivative_days=7)
    assert not may_issue_signed_urls(make_asset(), vibe, now=NOW, settings=cfg, creator_view=False)
    assert may_issue_signed_urls(make_asset(), vibe, now=NOW, settings=cfg, creator_view=True)


def test_creator_retention_window_eventually_closes() -> None:
    vibe = make_vibe(
        publication_status="expired",
        expires_at=NOW - timedelta(days=8),
    )
    cfg = settings(retention_processed_derivative_days=7)
    assert not may_issue_signed_urls(make_asset(), vibe, now=NOW, settings=cfg, creator_view=True)


def test_mediaconvert_adapter_is_a_production_seam_not_wired_locally() -> None:
    adapter = MediaConvertTranscoder(settings())
    assert adapter.provider == "mediaconvert"
    assert not adapter.available()
    local = LocalFfmpegTranscoder(settings())
    assert local.provider == "ffmpeg"
