"""Validation and sanitising transforms for uploaded media.

Ordering matters in two places and both are easy to get backwards:

1. **Orientation first, then strip metadata.** EXIF carries the rotation flag. If
   metadata is stripped before the pixels are rotated, every portrait photo from
   an iPhone is served sideways. If it is stripped after, the rotation has
   already been baked into the pixels.
2. **Validate before decode work.** Dimension and pixel-count limits are checked
   from the header so a 200 MP decompression bomb is rejected before Pillow
   allocates for it.

Nothing here trusts the client. The declared MIME type is advisory; the real
type comes from the file signature. The checksum is computed from the bytes on
disk, never taken from an ETag, which is not a content hash for multipart or
encrypted objects.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

CHUNK_BYTES = 1024 * 1024

IMAGE_VARIANTS: Final[tuple[tuple[str, int], ...]] = (
    ("image_1080", 1080),
    ("image_720", 720),
    ("thumbnail", 320),
)

WEBP_MIME = "image/webp"
MP4_MIME = "video/mp4"

VIDEO_TARGET_WIDTH = 1280
VIDEO_TARGET_HEIGHT = 720

#: ftyp brands we accept as MP4/QuickTime containers.
MP4_BRANDS: Final[frozenset[bytes]] = frozenset(
    {b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"dash", b"MSNV"}
)
QUICKTIME_BRANDS: Final[frozenset[bytes]] = frozenset({b"qt  "})


class MediaValidationError(Exception):
    """Content is not acceptable. Carries a stable reason code for the client."""

    def __init__(self, reason: str, message: str | None = None) -> None:
        super().__init__(message or reason)
        self.reason = reason


class MediaProcessingError(Exception):
    """A transform failed for an operational reason and may be retried."""

    def __init__(self, category: str, message: str | None = None) -> None:
        super().__init__(message or category)
        self.category = category


@dataclass(frozen=True)
class DerivativeOutput:
    variant_type: str
    path: Path
    mime_type: str
    byte_size: int
    checksum_sha256: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    codec: str | None = None


@dataclass(frozen=True)
class ProcessedMedia:
    detected_mime_type: str
    byte_size: int
    checksum_sha256: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    derivatives: list[DerivativeOutput] = field(default_factory=list)

    def primary_moderation_targets(self) -> list[DerivativeOutput]:
        """Sanitised outputs a moderation provider should look at."""
        preferred = ("image_1080", "video_poster", "thumbnail")
        ranked = sorted(
            self.derivatives,
            key=lambda d: (
                preferred.index(d.variant_type) if d.variant_type in preferred else len(preferred)
            ),
        )
        return [d for d in ranked if d.mime_type.startswith("image/")]


def sha256_file(path: Path) -> str:
    """Server-computed content hash. The only checksum the pipeline believes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def sniff_mime_type(path: Path) -> str | None:
    """Detect the container from its magic bytes."""
    with path.open("rb") as handle:
        head = handle.read(32)
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return WEBP_MIME
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in QUICKTIME_BRANDS:
            return "video/quicktime"
        if brand in MP4_BRANDS:
            return MP4_MIME
        # Unknown brand in a well-formed ftyp box: let ffprobe decide later.
        return MP4_MIME
    return None


class ImagePipeline:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def process(self, source: Path, workdir: Path) -> ProcessedMedia:
        byte_size = source.stat().st_size
        checksum = sha256_file(source)
        detected = sniff_mime_type(source)
        if detected is None or not detected.startswith("image/"):
            raise MediaValidationError("mime_not_an_image")

        width, height = self._validated_dimensions(source)
        derivatives = self._render_variants(source, workdir, (width, height))
        return ProcessedMedia(
            detected_mime_type=detected,
            byte_size=byte_size,
            checksum_sha256=checksum,
            width=width,
            height=height,
            derivatives=derivatives,
        )

    def _validated_dimensions(self, source: Path) -> tuple[int, int]:
        # Guard from the header before any decode happens.
        previous_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = self._settings.media_max_image_pixels
        try:
            with Image.open(source) as probe:
                width, height = probe.size
        except Image.DecompressionBombError as exc:
            raise MediaValidationError("image_decompression_bomb") from exc
        except UnidentifiedImageError as exc:
            raise MediaValidationError("image_unreadable") from exc
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit

        limit = self._settings.media_max_image_dimension
        if width <= 0 or height <= 0:
            raise MediaValidationError("image_dimensions_invalid")
        if width > limit or height > limit:
            raise MediaValidationError("image_dimensions_exceeded")
        if width * height > self._settings.media_max_image_pixels:
            raise MediaValidationError("image_pixel_budget_exceeded")
        return width, height

    def _render_variants(
        self, source: Path, workdir: Path, size: tuple[int, int]
    ) -> list[DerivativeOutput]:
        previous_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = self._settings.media_max_image_pixels
        try:
            with Image.open(source) as opened:
                opened.load()
                # Orientation first: the EXIF rotation flag disappears in the
                # next step, so it has to be applied to the pixels here.
                oriented = ImageOps.exif_transpose(opened) or opened
                sanitized = _strip_metadata(oriented)
        except Image.DecompressionBombError as exc:
            raise MediaValidationError("image_decompression_bomb") from exc
        except (OSError, UnidentifiedImageError) as exc:
            raise MediaValidationError("image_unreadable") from exc
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit

        outputs: list[DerivativeOutput] = []
        with sanitized:
            for variant_type, edge in IMAGE_VARIANTS:
                # Never upscale: a 1080 variant of a 200 px original is a bigger
                # file with no more detail in it.
                resized = _fit_within(sanitized, edge)
                destination = workdir / f"{variant_type}.webp"
                # A fresh image carries no info dict, so Pillow has no EXIF, XMP,
                # or ICC profile to copy into the output.
                resized.save(destination, format="WEBP", quality=82, method=4)
                outputs.append(
                    DerivativeOutput(
                        variant_type=variant_type,
                        path=destination,
                        mime_type=WEBP_MIME,
                        byte_size=destination.stat().st_size,
                        checksum_sha256=sha256_file(destination),
                        width=resized.width,
                        height=resized.height,
                        codec="webp",
                    )
                )
                resized.close()
        return outputs


def _fit_within(image: Image.Image, edge: int) -> Image.Image:
    if max(image.size) <= edge:
        return image.copy()
    return ImageOps.contain(image, (edge, edge), Image.Resampling.LANCZOS)


def _strip_metadata(image: Image.Image) -> Image.Image:
    """Copy pixels into a brand-new image, leaving EXIF/GPS/XMP/ICC behind."""
    mode = "RGBA" if image.mode in {"RGBA", "LA", "P"} else "RGB"
    converted = image.convert(mode)
    clean = Image.new(mode, converted.size)
    clean.paste(converted)
    if converted is not image:
        converted.close()
    # Belt and braces: assert the new image really has no metadata to copy.
    clean.info = {}
    return clean


class VideoPipeline:
    """Local ffmpeg transcode. Fixed argument vector, hard timeout, no HLS.

    Every path is server-generated inside an isolated temp directory and no
    client value ever reaches the argument list, so a filename cannot smuggle an
    ffmpeg option.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def available(self) -> bool:
        return bool(shutil.which(self._settings.ffmpeg_binary_path)) and bool(
            shutil.which(self._settings.ffprobe_binary_path)
        )

    async def process(self, source: Path, workdir: Path) -> ProcessedMedia:
        if not self.available():
            raise MediaProcessingError("ffmpeg_unavailable")

        # Hashing a 60 MB upload would stall the event loop for the worker's
        # whole poll interval, so the blocking reads happen on a thread.
        byte_size, checksum, detected = await asyncio.to_thread(_inspect_file, source)
        if detected is None or not detected.startswith("video/"):
            raise MediaValidationError("mime_not_a_video")

        probe = await self._probe(source)
        duration_ms = probe["duration_ms"]
        if duration_ms is None:
            raise MediaValidationError("video_duration_unknown")
        if duration_ms > self._settings.media_max_video_duration_ms:
            raise MediaValidationError("video_too_long")

        transcoded = workdir / "video_720.mp4"
        await self._run(
            [
                self._settings.ffmpeg_binary_path,
                *_FFMPEG_COMMON,
                "-i",
                str(source),
                "-t",
                f"{self._settings.media_max_video_duration_ms / 1000:.3f}",
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-vf",
                _SCALE_FILTER,
                "-c:v",
                "libx264",
                "-profile:v",
                "main",
                "-preset",
                "veryfast",
                "-crf",
                "26",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "96k",
                "-ac",
                "2",
                # Progressive download, not HLS: one file the client can seek.
                "-movflags",
                "+faststart",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-fflags",
                "+bitexact",
                str(transcoded),
            ]
        )
        poster = workdir / "video_poster.webp"
        await self._run(
            [
                self._settings.ffmpeg_binary_path,
                *_FFMPEG_COMMON,
                "-i",
                str(transcoded),
                "-frames:v",
                "1",
                "-vf",
                _SCALE_FILTER,
                "-map_metadata",
                "-1",
                str(poster),
            ]
        )

        output_probe = await self._probe(transcoded)
        derivatives = await asyncio.to_thread(
            _describe_video_outputs, transcoded, poster, output_probe
        )
        return ProcessedMedia(
            detected_mime_type=detected,
            byte_size=byte_size,
            checksum_sha256=checksum,
            width=probe["width"],
            height=probe["height"],
            duration_ms=duration_ms,
            derivatives=derivatives,
        )

    async def _probe(self, path: Path) -> dict[str, int | None]:
        stdout = await self._run(
            [
                self._settings.ffprobe_binary_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-protocol_whitelist",
                "file,crypto,data",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture=True,
        )
        try:
            payload: dict[str, Any] = json.loads(stdout or "{}")
        except json.JSONDecodeError as exc:
            raise MediaValidationError("video_unreadable") from exc

        streams = payload.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        if video is None:
            raise MediaValidationError("video_stream_missing")

        duration_seconds = _first_float(
            video.get("duration"), (payload.get("format") or {}).get("duration")
        )
        return {
            "width": _as_int(video.get("width")),
            "height": _as_int(video.get("height")),
            "duration_ms": int(duration_seconds * 1000) if duration_seconds is not None else None,
        }

    async def _run(self, argv: list[str], *, capture: bool = False) -> str:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self._settings.media_ffmpeg_timeout_seconds
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise MediaProcessingError("ffmpeg_timeout") from exc

        if process.returncode != 0:
            logger.warning(
                "ffmpeg_command_failed",
                tool=Path(argv[0]).name,
                returncode=process.returncode,
                stderr=stderr.decode("utf-8", "replace")[:500],
            )
            raise MediaValidationError("video_transcode_failed")
        return stdout.decode("utf-8", "replace") if capture else ""


def _inspect_file(path: Path) -> tuple[int, str, str | None]:
    return path.stat().st_size, sha256_file(path), sniff_mime_type(path)


def _describe_video_outputs(
    transcoded: Path, poster: Path, probe: dict[str, int | None]
) -> list[DerivativeOutput]:
    return [
        DerivativeOutput(
            variant_type="video_720",
            path=transcoded,
            mime_type=MP4_MIME,
            byte_size=transcoded.stat().st_size,
            checksum_sha256=sha256_file(transcoded),
            width=probe["width"],
            height=probe["height"],
            duration_ms=probe["duration_ms"],
            codec="h264",
        ),
        DerivativeOutput(
            variant_type="video_poster",
            path=poster,
            mime_type=WEBP_MIME,
            byte_size=poster.stat().st_size,
            checksum_sha256=sha256_file(poster),
            width=probe["width"],
            height=probe["height"],
            codec="webp",
        ),
    ]


# Disable network/demuxer protocols so a crafted container cannot pull remote
# payloads. Only local file access is required for quarantine originals.
_FFMPEG_COMMON: Final[tuple[str, ...]] = (
    "-nostdin",
    "-hide_banner",
    "-loglevel",
    "error",
    "-y",
    "-protocol_whitelist",
    "file,crypto,data",
)

_SCALE_FILTER: Final[str] = (
    f"scale='min({VIDEO_TARGET_WIDTH},iw)':'min({VIDEO_TARGET_HEIGHT},ih)'"
    ":force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2"
)


def _as_int(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _first_float(*values: object) -> float | None:
    for value in values:
        try:
            parsed = float(str(value))
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None
