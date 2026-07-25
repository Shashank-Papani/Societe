"""Who may post a Live Vibe, and with what attribution.

The lease is the only accepted proof of presence. Every test here asks the same
question in a different way: does an answer other than "verified, at this venue,
right now, from this device" ever produce a presigned URL?
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from redis.exceptions import RedisError

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import User, UserDevice, UserPrivacySettings
from app.modules.media.authz import MediaRateLimiter, validate_declared_media
from app.modules.media.schemas import CompleteUploadRequest, CreateUploadRequest
from app.modules.presence.leases import LeaseSnapshot
from app.modules.presence.service import PresenceService

VENUE_A = UUID("11111111-1111-1111-1111-111111111111")
VENUE_B = UUID("22222222-2222-2222-2222-222222222222")

NOW = datetime(2026, 7, 24, 4, 30, tzinfo=UTC)


class FakeScript:
    async def __call__(self, *, keys: list[str], args: list[str]) -> list[str]:
        return ["", ""]


class FakeRedis:
    """Only the surface the lease store and rate limiter touch."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.counters: dict[str, int] = {}
        self.raise_on_incr = False

    def register_script(self, _source: str) -> FakeScript:
        return FakeScript()

    async def hgetall(self, key: str) -> dict[str, str]:
        return self.hashes.get(key, {})

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._keys: list[str] = []

    def incr(self, key: str) -> None:
        self._keys.append(key)

    def expire(self, key: str, seconds: int) -> None:
        return None

    async def execute(self) -> list[int]:
        if self._redis.raise_on_incr:
            raise RedisError("valkey down")
        results = []
        for key in self._keys:
            self._redis.counters[key] = self._redis.counters.get(key, 0) + 1
            results.append(self._redis.counters[key])
        return results


class StubLeaseStore:
    def __init__(self, lease: LeaseSnapshot | None, *, error: bool = False) -> None:
        self._lease = lease
        self._error = error

    async def read(self, user_id: UUID) -> LeaseSnapshot | None:
        if self._error:
            raise RedisError("valkey down")
        return self._lease


def make_user(**overrides: Any) -> User:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "auth_subject": "sub-test",
        "handle": "poster",
        "display_name": "Poster",
        "account_status": "active",
        "onboarding_state": "completed",
        "age_verified": True,
        "deleted_at": None,
    }
    fields.update(overrides)
    return User(**fields)


def make_device(user: User, **overrides: Any) -> UserDevice:
    fields: dict[str, Any] = {
        "id": uuid4(),
        "user_id": user.id,
        "platform": "ios",
        "installation_id": uuid4(),
        "revoked_at": None,
    }
    fields.update(overrides)
    return UserDevice(**fields)


def make_lease(**overrides: Any) -> LeaseSnapshot:
    fields: dict[str, Any] = {
        "user_id": uuid4(),
        "venue_id": VENUE_A,
        "check_in_id": uuid4(),
        "state": "verified",
        "confidence": 90,
        "verification_level": "standard",
        "ghost_mode": False,
        "discoverable": True,
        "verified_until": NOW + timedelta(seconds=90),
        "grace_until": NOW + timedelta(seconds=400),
        "lease_version": 3,
    }
    fields.update(overrides)
    return LeaseSnapshot(**fields)


def make_service(
    lease: LeaseSnapshot | None, *, lease_error: bool = False, **setting_overrides: Any
) -> PresenceService:
    settings = Settings(auth_provider="cognito", **setting_overrides)
    service = PresenceService(None, FakeRedis(), settings)  # type: ignore[arg-type]
    service._leases = StubLeaseStore(lease, error=lease_error)  # type: ignore[assignment]
    return service


# ------------------------------------------------------------------ allow path


async def test_verified_lease_at_the_requested_venue_authorizes_posting() -> None:
    user = make_user()
    decision = await make_service(make_lease()).can_post_live_vibe(
        user, VENUE_A, make_device(user), now=NOW
    )
    assert decision.allowed
    assert decision.venue_id == VENUE_A
    assert decision.attribution_mode == "attributed"
    assert decision.lease_state == "verified"


async def test_ghost_mode_posts_anonymously_but_is_not_blocked() -> None:
    """Ghost Mode is an attribution setting, not a posting permission."""
    user = make_user()
    decision = await make_service(make_lease(ghost_mode=True)).can_post_live_vibe(
        user, VENUE_A, make_device(user), now=NOW
    )
    assert decision.allowed
    assert decision.attribution_mode == "anonymous"


async def test_undiscoverable_user_may_still_post() -> None:
    user = make_user()
    decision = await make_service(
        make_lease(discoverable=False, ghost_mode=False)
    ).can_post_live_vibe(user, VENUE_A, make_device(user), now=NOW)
    assert decision.allowed
    assert decision.attribution_mode == "attributed"


async def test_allow_calling_cards_false_does_not_block_live_vibe_posting() -> None:
    """Calling Card preference is a separate product surface from Live Vibes."""
    user = make_user()
    user.privacy = UserPrivacySettings(
        user_id=user.id,
        ghost_mode=False,
        discoverable_in_venue=True,
        allow_calling_cards=False,
        show_social_links_after_accept=False,
        analytics_opt_out=False,
    )
    decision = await make_service(make_lease()).can_post_live_vibe(
        user, VENUE_A, make_device(user), now=NOW
    )
    assert decision.allowed


async def test_ghost_plus_undiscoverable_still_allows_anonymous_posting() -> None:
    user = make_user()
    decision = await make_service(
        make_lease(ghost_mode=True, discoverable=False)
    ).can_post_live_vibe(user, VENUE_A, make_device(user), now=NOW)
    assert decision.allowed
    assert decision.attribution_mode == "anonymous"


# ----------------------------------------------------------------- reject path


@pytest.mark.parametrize(
    "lease_state",
    ["provisional", "degraded", "refresh_required", "ambiguous", "exited", "revoked", "outside"],
)
async def test_every_non_verified_lease_state_refuses(lease_state: str) -> None:
    user = make_user()
    decision = await make_service(make_lease(state=lease_state)).can_post_live_vibe(
        user, VENUE_A, make_device(user), now=NOW
    )
    assert not decision.allowed
    assert decision.reason == f"presence_{lease_state}"
    assert decision.attribution_mode is None


async def test_expired_verified_window_refuses_even_though_state_says_verified() -> None:
    """A cached hash outliving its window is not evidence of being there."""
    lease = make_lease(verified_until=NOW - timedelta(seconds=1))
    user = make_user()
    decision = await make_service(lease).can_post_live_vibe(
        user, VENUE_A, make_device(user), now=NOW
    )
    assert not decision.allowed
    assert decision.reason == "presence_refresh_required"


async def test_lease_at_a_different_venue_refuses() -> None:
    user = make_user()
    decision = await make_service(make_lease(venue_id=VENUE_B)).can_post_live_vibe(
        user, VENUE_A, make_device(user), now=NOW
    )
    assert not decision.allowed
    assert decision.reason == "presence_venue_mismatch"


async def test_missing_lease_refuses() -> None:
    user = make_user()
    decision = await make_service(None).can_post_live_vibe(
        user, VENUE_A, make_device(user), now=NOW
    )
    assert not decision.allowed
    assert decision.reason == "presence_refresh_required"


async def test_lease_without_check_in_refuses() -> None:
    user = make_user()
    decision = await make_service(make_lease(check_in_id=None)).can_post_live_vibe(
        user, VENUE_A, make_device(user), now=NOW
    )
    assert not decision.allowed
    assert decision.reason == "presence_refresh_required"


async def test_unreachable_valkey_refuses_rather_than_assuming_presence() -> None:
    user = make_user()
    decision = await make_service(None, lease_error=True).can_post_live_vibe(
        user, VENUE_A, make_device(user), now=NOW
    )
    assert not decision.allowed
    assert decision.reason == "presence_cache_unavailable"


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"account_status": "suspended"}, "account_not_active"),
        ({"account_status": "deactivated"}, "account_not_active"),
        ({"deleted_at": NOW}, "account_not_active"),
    ],
)
async def test_inactive_accounts_cannot_post(overrides: dict[str, Any], expected: str) -> None:
    user = make_user(**overrides)
    decision = await make_service(make_lease()).can_post_live_vibe(
        user, VENUE_A, make_device(user), now=NOW
    )
    assert not decision.allowed
    assert decision.reason == expected


async def test_revoked_device_cannot_post() -> None:
    user = make_user()
    device = make_device(user, revoked_at=NOW - timedelta(hours=1))
    decision = await make_service(make_lease()).can_post_live_vibe(user, VENUE_A, device, now=NOW)
    assert not decision.allowed
    assert decision.reason == "device_revoked"


async def test_device_belonging_to_another_account_cannot_post() -> None:
    user = make_user()
    stranger_device = make_device(make_user(auth_subject="sub-other", handle="other"))
    decision = await make_service(make_lease()).can_post_live_vibe(
        user, VENUE_A, stranger_device, now=NOW
    )
    assert not decision.allowed
    assert decision.reason == "device_not_owned"


# ----------------------------------------------------------- declared payloads


def upload_request(**overrides: Any) -> CreateUploadRequest:
    payload: dict[str, Any] = {
        "venue_id": str(VENUE_A),
        "device_id": str(uuid4()),
        "media_type": "image",
        "mime_type": "image/jpeg",
        "byte_size": 1024,
    }
    payload.update(overrides)
    return CreateUploadRequest.model_validate(payload)


def test_caption_html_and_control_characters_are_stripped() -> None:
    request = CreateUploadRequest.model_validate(
        {
            "venue_id": str(VENUE_A),
            "device_id": str(uuid4()),
            "media_type": "image",
            "mime_type": "image/jpeg",
            "byte_size": 1024,
            "caption": "hello\x00 <b>world</b>",
            "vibe_tags": ["  Night\x07Out  ", "NightOut"],
        }
    )
    assert request.caption == "hello world"
    assert request.vibe_tags == ["nightout"]


def test_declared_mime_must_match_the_declared_media_type() -> None:
    settings = Settings(auth_provider="cognito")
    with pytest.raises(AppError) as exc:
        validate_declared_media(upload_request(mime_type="video/mp4"), settings)
    assert exc.value.code == "MEDIA_TYPE_UNSUPPORTED"
    assert exc.value.status_code == 415


def test_image_and_video_size_ceilings_are_separate() -> None:
    settings = Settings(auth_provider="cognito")
    oversized_image = upload_request(byte_size=settings.media_max_image_bytes + 1)
    with pytest.raises(AppError) as exc:
        validate_declared_media(oversized_image, settings)
    assert exc.value.code == "MEDIA_TOO_LARGE"

    # The same byte count is fine for a video, which has its own ceiling.
    validate_declared_media(
        upload_request(
            media_type="video",
            mime_type="video/mp4",
            byte_size=settings.media_max_image_bytes + 1,
        ),
        settings,
    )


def test_caption_and_tag_limits_are_enforced_before_a_url_is_minted() -> None:
    settings = Settings(auth_provider="cognito")
    with pytest.raises(AppError) as caption_exc:
        validate_declared_media(
            upload_request(caption="x" * (settings.media_caption_max_length + 1)), settings
        )
    assert caption_exc.value.code == "CAPTION_TOO_LONG"

    with pytest.raises(AppError) as tags_exc:
        validate_declared_media(
            upload_request(vibe_tags=[f"tag{i}" for i in range(settings.media_max_vibe_tags + 1)]),
            settings,
        )
    assert tags_exc.value.code == "TOO_MANY_VIBE_TAGS"

    with pytest.raises(AppError) as long_tag_exc:
        validate_declared_media(
            upload_request(vibe_tags=["y" * (settings.media_vibe_tag_max_length + 1)]), settings
        )
    assert long_tag_exc.value.code == "VIBE_TAG_TOO_LONG"


def test_tags_are_lowercased_and_deduplicated() -> None:
    request = upload_request(vibe_tags=[" Rooftop ", "rooftop", "LIVE-DJ", ""])
    assert request.vibe_tags == ["rooftop", "live-dj"]


def test_blank_caption_becomes_absent() -> None:
    assert upload_request(caption="   ").caption is None


@pytest.mark.parametrize("field", ["upload_id", "parts", "part_number", "multipart"])
def test_multipart_fields_are_rejected_rather_than_ignored(field: str) -> None:
    """A silently ignored multipart intent would look like a working upload."""
    with pytest.raises(ValidationError):
        upload_request(**{field: "anything"})
    with pytest.raises(ValidationError):
        CompleteUploadRequest.model_validate({"device_id": str(uuid4()), field: "anything"})


def test_declared_checksum_must_be_a_sha256_hex_digest() -> None:
    with pytest.raises(ValidationError):
        upload_request(checksum_sha256="not-a-digest")
    assert upload_request(checksum_sha256="a" * 64).checksum_sha256 == "a" * 64


# ------------------------------------------------------------- rate limits


async def test_upload_rate_limit_returns_429_with_a_scope() -> None:
    settings = Settings(
        auth_provider="cognito",
        media_upload_rate_limit_per_user_per_hour=2,
        media_upload_rate_limit_per_user_per_venue_per_hour=2,
    )
    limiter = MediaRateLimiter(FakeRedis(), settings)  # type: ignore[arg-type]
    user_id = uuid4()
    for _ in range(2):
        await limiter.check_upload(user_id=user_id, venue_id=VENUE_A, now=NOW)
    with pytest.raises(AppError) as exc:
        await limiter.check_upload(user_id=user_id, venue_id=VENUE_A, now=NOW)
    assert exc.value.status_code == 429
    assert exc.value.details["scope"] == "user"


async def test_per_venue_budget_is_tighter_than_the_account_budget() -> None:
    settings = Settings(
        auth_provider="cognito",
        media_upload_rate_limit_per_user_per_hour=10,
        media_upload_rate_limit_per_user_per_venue_per_hour=1,
    )
    limiter = MediaRateLimiter(FakeRedis(), settings)  # type: ignore[arg-type]
    user_id = uuid4()
    await limiter.check_upload(user_id=user_id, venue_id=VENUE_A, now=NOW)
    # A different venue still has room; the same venue does not.
    await limiter.check_upload(user_id=user_id, venue_id=VENUE_B, now=NOW)
    with pytest.raises(AppError) as exc:
        await limiter.check_upload(user_id=user_id, venue_id=VENUE_A, now=NOW)
    assert exc.value.details["scope"] == "user_venue"


async def test_rate_limiter_fails_closed_when_valkey_is_down() -> None:
    """Posting already requires a live lease, so an outage cannot mean "allow"."""
    redis = FakeRedis()
    redis.raise_on_incr = True
    limiter = MediaRateLimiter(redis, Settings(auth_provider="cognito"))  # type: ignore[arg-type]
    with pytest.raises(AppError) as exc:
        await limiter.check_upload(user_id=uuid4(), venue_id=VENUE_A, now=NOW)
    assert exc.value.status_code == 503
    assert exc.value.code == "MEDIA_RATE_LIMIT_UNAVAILABLE"
