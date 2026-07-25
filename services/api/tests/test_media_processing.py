"""Sanitising transforms, scanning, and moderation.

The fixtures are generated per test (see `packages/test-fixtures`) because the
inputs that matter here are hostile ones — EXIF GPS, a decompression bomb, an
EICAR pattern — and none of those belong in the repository as files.
"""

from __future__ import annotations

import hashlib
import shutil
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from societe_media_fixtures import (
    GPS_IFD_TAG,
    ORIENTATION_TAG,
    write_jpeg_with_exif_gps,
    write_mp4,
    write_oversized_png,
    write_png,
    write_webp,
)

from app.core.config import Settings
from app.modules.media.malware import (
    EICAR_SIGNATURE,
    FailClosedMalwareScanner,
    NoOpMalwareScanner,
    build_malware_scanner,
)
from app.modules.media.moderation import (
    DeterministicFakeModerationProvider,
    ModerationAsset,
    build_moderation_provider,
)
from app.modules.media.processors import (
    ImagePipeline,
    MediaProcessingError,
    MediaValidationError,
    VideoPipeline,
    sha256_file,
    sniff_mime_type,
)
from app.modules.media.storage import derivative_object_key, quarantine_object_key


def settings(**overrides: object) -> Settings:
    return Settings(auth_provider="cognito", **overrides)  # type: ignore[arg-type]


def outdir(tmp_path: Path) -> Path:
    out = tmp_path / "out"
    out.mkdir()
    return out


# ------------------------------------------------------------------- detection


def test_container_is_detected_from_magic_bytes_not_the_declared_type(tmp_path: Path) -> None:
    jpeg = write_jpeg_with_exif_gps(tmp_path / "a.jpg")
    # A client-chosen extension says nothing; the signature does.
    disguised = tmp_path / "totally_a_video.mp4"
    shutil.copyfile(jpeg, disguised)
    assert sniff_mime_type(disguised) == "image/jpeg"
    assert sniff_mime_type(write_png(tmp_path / "b.png")) == "image/png"
    assert sniff_mime_type(write_webp(tmp_path / "c.webp")) == "image/webp"


def test_unrecognised_bytes_have_no_detected_type(tmp_path: Path) -> None:
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"\x00\x01\x02not-a-media-container")
    assert sniff_mime_type(junk) is None


def test_checksum_is_computed_from_the_bytes_on_disk(tmp_path: Path) -> None:
    """Never an ETag: that is not a content hash for multipart or SSE objects."""
    source = write_png(tmp_path / "hash.png")
    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    assert sha256_file(source) == expected


# ----------------------------------------------------------------- image paths


def test_orientation_is_baked_in_before_metadata_is_discarded(tmp_path: Path) -> None:
    """A landscape file marked "rotate 90" must come out portrait, tag-free."""
    source = write_jpeg_with_exif_gps(tmp_path / "oriented.jpg", width=240, height=120)
    with Image.open(source) as original:
        assert original.size == (240, 120)
        assert original.getexif()[ORIENTATION_TAG] == 6

    processed = ImagePipeline(settings()).process(source, outdir(tmp_path))
    thumbnail = next(d for d in processed.derivatives if d.variant_type == "thumbnail")
    assert thumbnail.height > thumbnail.width


def test_derivatives_carry_no_exif_or_gps(tmp_path: Path) -> None:
    source = write_jpeg_with_exif_gps(tmp_path / "gps.jpg")
    with Image.open(source) as original:
        assert GPS_IFD_TAG in original.getexif()

    processed = ImagePipeline(settings()).process(source, outdir(tmp_path))
    assert processed.derivatives
    for derivative in processed.derivatives:
        with Image.open(derivative.path) as output:
            exif = output.getexif()
            assert GPS_IFD_TAG not in exif
            assert ORIENTATION_TAG not in exif
            assert "exif" not in output.info
            assert "icc_profile" not in output.info


def test_three_webp_variants_are_produced_within_their_edge_budgets(tmp_path: Path) -> None:
    source = write_png(tmp_path / "big.png", width=2000, height=1500)
    processed = ImagePipeline(settings()).process(source, outdir(tmp_path))

    by_type = {d.variant_type: d for d in processed.derivatives}
    assert set(by_type) == {"image_1080", "image_720", "thumbnail"}
    for variant, edge in (("image_1080", 1080), ("image_720", 720), ("thumbnail", 320)):
        derivative = by_type[variant]
        assert derivative.mime_type == "image/webp"
        assert derivative.byte_size > 0
        assert derivative.width is not None and derivative.height is not None
        assert max(derivative.width, derivative.height) <= edge
        assert derivative.checksum_sha256 == sha256_file(derivative.path)


def test_upscaling_is_avoided_for_a_small_original(tmp_path: Path) -> None:
    source = write_png(tmp_path / "small.png", width=200, height=200)
    processed = ImagePipeline(settings()).process(source, outdir(tmp_path))
    large = next(d for d in processed.derivatives if d.variant_type == "image_1080")
    assert (large.width, large.height) == (200, 200)


def test_original_probe_records_type_size_and_checksum(tmp_path: Path) -> None:
    source = write_png(tmp_path / "probe.png", width=320, height=240)
    processed = ImagePipeline(settings()).process(source, outdir(tmp_path))
    assert processed.detected_mime_type == "image/png"
    assert processed.byte_size == source.stat().st_size
    assert processed.checksum_sha256 == sha256_file(source)
    assert (processed.width, processed.height) == (320, 240)


def test_oversized_dimensions_are_refused(tmp_path: Path) -> None:
    source = write_png(tmp_path / "wide.png", width=400, height=100)
    with pytest.raises(MediaValidationError) as exc:
        ImagePipeline(settings(media_max_image_dimension=200)).process(source, outdir(tmp_path))
    assert exc.value.reason == "image_dimensions_exceeded"


def test_decompression_bomb_is_refused_before_it_is_decoded(tmp_path: Path) -> None:
    """A few kilobytes on disk, hundreds of megapixels once decoded."""
    source = write_oversized_png(tmp_path / "bomb.png", edge=10)
    assert source.stat().st_size < 1_000_000
    with pytest.raises(MediaValidationError) as exc:
        ImagePipeline(settings()).process(source, outdir(tmp_path))
    assert exc.value.reason in {"image_decompression_bomb", "image_dimensions_exceeded"}


def test_pixel_budget_is_enforced_independently_of_each_edge(tmp_path: Path) -> None:
    source = write_png(tmp_path / "area.png", width=400, height=400)
    with pytest.raises(MediaValidationError) as exc:
        ImagePipeline(settings(media_max_image_pixels=100_000)).process(source, outdir(tmp_path))
    assert exc.value.reason in {"image_pixel_budget_exceeded", "image_decompression_bomb"}


def test_a_video_is_not_accepted_by_the_image_pipeline(tmp_path: Path) -> None:
    fake = tmp_path / "clip.mp4"
    fake.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 64)
    with pytest.raises(MediaValidationError) as exc:
        ImagePipeline(settings()).process(fake, outdir(tmp_path))
    assert exc.value.reason == "mime_not_an_image"


def test_truncated_image_is_reported_as_unreadable(tmp_path: Path) -> None:
    source = write_png(tmp_path / "trunc.png")
    truncated = tmp_path / "half.png"
    truncated.write_bytes(source.read_bytes()[:60])
    with pytest.raises(MediaValidationError) as exc:
        ImagePipeline(settings()).process(truncated, outdir(tmp_path))
    assert exc.value.reason in {"image_unreadable", "image_dimensions_invalid"}


# ----------------------------------------------------------------- video paths

ffmpeg_required = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe are not on PATH (they are baked into the API image)",
)


@ffmpeg_required
async def test_video_produces_one_progressive_mp4_and_a_poster(tmp_path: Path) -> None:
    source = write_mp4(tmp_path / "clip.mp4", seconds=2)
    assert source is not None
    processed = await VideoPipeline(settings()).process(source, outdir(tmp_path))

    by_type = {d.variant_type: d for d in processed.derivatives}
    assert set(by_type) == {"video_720", "video_poster"}
    assert by_type["video_720"].mime_type == "video/mp4"
    assert by_type["video_720"].codec == "h264"
    assert by_type["video_poster"].mime_type == "image/webp"
    assert processed.duration_ms is not None and processed.duration_ms >= 1_900

    # No HLS locally: a single seekable file, not a playlist and segments.
    produced = {path.suffix for path in outdir(tmp_path).iterdir()}
    assert ".m3u8" not in produced
    assert ".ts" not in produced


@ffmpeg_required
async def test_clip_longer_than_the_limit_is_refused(tmp_path: Path) -> None:
    source = write_mp4(tmp_path / "long.mp4", seconds=3)
    assert source is not None
    with pytest.raises(MediaValidationError) as exc:
        await VideoPipeline(settings(media_max_video_duration_ms=1_000)).process(
            source, outdir(tmp_path)
        )
    assert exc.value.reason == "video_too_long"


@ffmpeg_required
async def test_a_still_image_is_not_accepted_by_the_video_pipeline(tmp_path: Path) -> None:
    source = write_png(tmp_path / "still.png")
    with pytest.raises(MediaValidationError) as exc:
        await VideoPipeline(settings()).process(source, outdir(tmp_path))
    assert exc.value.reason == "mime_not_a_video"


@ffmpeg_required
async def test_malformed_video_bytes_are_rejected(tmp_path: Path) -> None:
    junk = tmp_path / "broken.mp4"
    junk.write_bytes(b"ftypisom" + b"\x00" * 64)
    with pytest.raises((MediaValidationError, MediaProcessingError)):
        await VideoPipeline(settings()).process(junk, outdir(tmp_path))


@ffmpeg_required
async def test_transcode_timeout_is_operational_not_a_content_rejection(tmp_path: Path) -> None:
    """A timeout means "try again", not "this user's clip is bad"."""
    source = write_mp4(tmp_path / "slow.mp4", seconds=2)
    assert source is not None
    with pytest.raises(MediaProcessingError) as exc:
        await VideoPipeline(settings(media_ffmpeg_timeout_seconds=0)).process(
            source, outdir(tmp_path)
        )
    assert exc.value.category == "ffmpeg_timeout"


async def test_missing_ffmpeg_is_reported_as_retryable(tmp_path: Path) -> None:
    pipeline = VideoPipeline(settings(ffmpeg_binary_path="societe-no-such-ffmpeg"))
    assert not pipeline.available()
    with pytest.raises(MediaProcessingError) as exc:
        await pipeline.process(tmp_path / "missing.mp4", outdir(tmp_path))
    assert exc.value.category == "ffmpeg_unavailable"


# --------------------------------------------------------------------- malware


async def test_eicar_pattern_is_reported_infected(tmp_path: Path) -> None:
    sample = tmp_path / "eicar.bin"
    sample.write_bytes(EICAR_SIGNATURE + b"-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*")
    result = await NoOpMalwareScanner().scan(sample)
    assert result.verdict == "infected"
    assert result.signature == "EICAR-Test"
    assert not result.is_clean


async def test_ordinary_media_scans_clean(tmp_path: Path) -> None:
    result = await NoOpMalwareScanner().scan(write_png(tmp_path / "clean.png"))
    assert result.is_clean


async def test_an_unimplemented_scanner_reports_unavailable_never_clean(tmp_path: Path) -> None:
    result = await FailClosedMalwareScanner("clamav").scan(write_png(tmp_path / "x.png"))
    assert result.verdict == "unavailable"
    assert not result.is_clean


def test_noop_scanner_is_refused_outside_development() -> None:
    staging = settings().model_copy(update={"app_env": "staging"})
    with pytest.raises(RuntimeError) as exc:
        build_malware_scanner(staging)
    assert "MEDIA_MALWARE_SCANNER" in str(exc.value)


def test_noop_scanner_is_available_in_development_and_test() -> None:
    for env in ("development", "test"):
        scanner = build_malware_scanner(settings().model_copy(update={"app_env": env}))
        assert scanner.provider == "noop"


def test_configuring_the_noop_scanner_for_production_fails_validation() -> None:
    with pytest.raises(ValueError, match="MEDIA_MALWARE_SCANNER"):
        Settings(
            app_env="production",
            auth_provider="cognito",
            media_malware_scanner="noop",
            ff_location_simulator=False,
        )


def test_configuring_the_fake_moderator_for_production_fails_validation() -> None:
    with pytest.raises(ValueError, match="MEDIA_MODERATION_PROVIDER"):
        Settings(
            app_env="production",
            auth_provider="cognito",
            media_malware_scanner="clamav",
            media_moderation_provider="fake",
            ff_location_simulator=False,
        )


# ------------------------------------------------------------------ moderation


def moderation_asset(tmp_path: Path, **overrides: object) -> ModerationAsset:
    fields: dict[str, object] = {
        "media_asset_id": uuid4(),
        "media_type": "image",
        "caption": "great set tonight",
        "vibe_tags": ["rooftop"],
        "derivative_paths": [write_png(tmp_path / "reviewable.png")],
        "derivative_checksums": ["a" * 64],
    }
    fields.update(overrides)
    return ModerationAsset(**fields)  # type: ignore[arg-type]


async def test_clean_content_is_approved_with_a_policy_version(tmp_path: Path) -> None:
    provider = DeterministicFakeModerationProvider(settings())
    result = await provider.moderate(moderation_asset(tmp_path))
    assert result.decision == "approved"
    assert result.case_status == "auto_approved"
    assert result.policy_version == settings().media_moderation_policy_version


@pytest.mark.parametrize(
    ("overrides", "decision", "case_status"),
    [
        ({"caption": "party [moderation:reject]"}, "rejected", "auto_rejected"),
        ({"vibe_tags": ["moderation-reject"]}, "rejected", "auto_rejected"),
        ({"caption": "hmm [moderation:review]"}, "manual_review", "needs_review"),
        ({"vibe_tags": ["moderation-review"]}, "manual_review", "needs_review"),
    ],
)
async def test_markers_drive_deterministic_decisions(
    tmp_path: Path, overrides: dict[str, object], decision: str, case_status: str
) -> None:
    provider = DeterministicFakeModerationProvider(settings())
    result = await provider.moderate(moderation_asset(tmp_path, **overrides))
    assert result.decision == decision
    assert result.case_status == case_status
    assert result.signals and isinstance(result.signals[0].confidence, Decimal)


async def test_the_same_input_always_yields_the_same_decision(tmp_path: Path) -> None:
    provider = DeterministicFakeModerationProvider(settings())
    asset = moderation_asset(tmp_path, caption="ordinary night")
    first = await provider.moderate(asset)
    second = await provider.moderate(asset)
    assert (first.decision, first.signals[0].category) == (
        second.decision,
        second.signals[0].category,
    )


async def test_nothing_sanitised_to_review_means_no_approval(tmp_path: Path) -> None:
    provider = DeterministicFakeModerationProvider(settings())
    result = await provider.moderate(
        moderation_asset(tmp_path, derivative_paths=[], derivative_checksums=[])
    )
    assert result.decision == "manual_review"
    assert result.signals[0].category == "no_reviewable_derivative"


async def test_asynchronous_video_moderation_is_not_pretended_to_work(tmp_path: Path) -> None:
    provider = DeterministicFakeModerationProvider(settings())
    with pytest.raises(NotImplementedError):
        await provider.start_video_moderation(moderation_asset(tmp_path))


def test_fake_moderation_provider_is_refused_outside_development() -> None:
    with pytest.raises(RuntimeError, match="MEDIA_MODERATION_PROVIDER"):
        build_moderation_provider(settings().model_copy(update={"app_env": "staging"}))


def test_an_unimplemented_moderation_provider_refuses_to_start() -> None:
    """Better a failed boot than a queue of media that can never publish."""
    with pytest.raises(RuntimeError, match="not implemented"):
        build_moderation_provider(
            settings().model_copy(update={"media_moderation_provider": "rekognition"})
        )


# ------------------------------------------------------------------ object keys


def test_quarantine_keys_are_scoped_to_the_owner_and_chosen_by_the_server() -> None:
    owner, asset = uuid4(), uuid4()
    key = quarantine_object_key(owner_user_id=owner, asset_id=asset, mime_type="image/jpeg")
    assert key == f"quarantine/u{owner}/{asset}/original.jpg"


def test_derivative_keys_are_namespaced_by_generation() -> None:
    asset = uuid4()
    first = derivative_object_key(
        asset_id=asset, generation=1, variant_type="image_1080", mime_type="image/webp"
    )
    assert first == f"processed/{asset}/g1/image_1080.webp"
    # A reprocess writes elsewhere, so a live signed URL keeps resolving.
    second = derivative_object_key(
        asset_id=asset, generation=2, variant_type="image_1080", mime_type="image/webp"
    )
    assert second != first
    assert second == f"processed/{asset}/g2/image_1080.webp"


def test_unknown_mime_types_do_not_produce_a_misleading_extension() -> None:
    key = quarantine_object_key(
        owner_user_id=uuid4(), asset_id=uuid4(), mime_type="application/x-unknown"
    )
    assert key.endswith("original.bin")
