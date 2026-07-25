"""Synthetic media fixtures for the Phase 3 pipeline.

Everything is generated, never committed. Real user media must not enter the
repository, and a committed binary blob is impossible to review — so the tests
build what they need at run time and this module is the single description of
those inputs.

The JPEG deliberately carries EXIF orientation *and* GPS coordinates: those two
tags are what the sanitising step exists to handle, so a fixture without them
would let a regression through.

CLI:

    python -m societe_media_fixtures --out ./packages/test-fixtures/output
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw
from PIL.TiffImagePlugin import IFDRational

# Rotate 90° clockwise on display. A correct pipeline bakes this into the pixels
# before it discards the tag.
EXIF_ORIENTATION_ROTATE_90 = 6
ORIENTATION_TAG = 0x0112
GPS_IFD_TAG = 0x8825
DESCRIPTION_TAG = 0x010E

# Downtown Los Angeles, so a leaked location is obviously a leak in tests.
GPS_LATITUDE = (IFDRational(34), IFDRational(3), IFDRational(8))
GPS_LONGITUDE = (IFDRational(118), IFDRational(14), IFDRational(37))

FFMPEG_TEST_DURATION_SECONDS = 2


def _draw_gradient(width: int, height: int) -> Image.Image:
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for x in range(width):
        shade = int(255 * x / max(width - 1, 1))
        draw.line([(x, 0), (x, height)], fill=(shade, 64, 255 - shade))
    # An off-centre marker makes an incorrect rotation visible to a human too.
    draw.rectangle([(0, 0), (width // 6, height // 6)], fill=(255, 255, 0))
    return image


def build_exif() -> Image.Exif:
    exif = Image.Exif()
    exif[ORIENTATION_TAG] = EXIF_ORIENTATION_ROTATE_90
    exif[DESCRIPTION_TAG] = "societe-synthetic-fixture"
    exif[GPS_IFD_TAG] = {
        1: "N",
        2: GPS_LATITUDE,
        3: "W",
        4: GPS_LONGITUDE,
    }
    return exif


def write_jpeg_with_exif_gps(destination: Path, *, width: int = 240, height: int = 120) -> Path:
    """Landscape JPEG whose EXIF asks for a 90° rotation, plus GPS tags."""
    image = _draw_gradient(width, height)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="JPEG", quality=90, exif=build_exif())
    image.close()
    return destination


def write_png(destination: Path, *, width: int = 200, height: int = 200) -> Path:
    image = _draw_gradient(width, height)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG")
    image.close()
    return destination


def write_webp(destination: Path, *, width: int = 200, height: int = 150) -> Path:
    image = _draw_gradient(width, height)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="WEBP", quality=85)
    image.close()
    return destination


def write_oversized_png(destination: Path, *, edge: int = 40) -> Path:
    """Small file, enormous declared canvas: the decompression-bomb shape.

    A one-colour PNG of this size compresses to a few kilobytes while decoding to
    hundreds of megapixels, which is exactly the input the pixel budget rejects.
    """
    image = Image.new("RGB", (edge * 1000, edge * 1000), (7, 7, 7))
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True)
    image.close()
    return destination


def ffmpeg_available(ffmpeg: str = "ffmpeg") -> bool:
    return shutil.which(ffmpeg) is not None


def write_mp4(
    destination: Path,
    *,
    seconds: int = FFMPEG_TEST_DURATION_SECONDS,
    ffmpeg: str = "ffmpeg",
) -> Path | None:
    """Synthetic H.264/AAC clip. Returns None when ffmpeg is unavailable."""
    if not ffmpeg_available(ffmpeg):
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=640x360:rate=24:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(destination),
        ],
        check=True,
        capture_output=True,
    )
    return destination


def write_all(output_dir: Path) -> dict[str, Path]:
    created = {
        "jpeg_exif_gps": write_jpeg_with_exif_gps(output_dir / "sample_exif_gps.jpg"),
        "png": write_png(output_dir / "sample.png"),
        "webp": write_webp(output_dir / "sample.webp"),
    }
    mp4 = write_mp4(output_dir / "sample.mp4")
    if mp4 is not None:
        created["mp4"] = mp4
    return created


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "output",
        help="Directory to write fixtures into (gitignored).",
    )
    args = parser.parse_args()
    created = write_all(args.out)
    for name, path in created.items():
        print(f"{name}: {path} ({path.stat().st_size} bytes)")
    if "mp4" not in created:
        print("mp4: skipped (ffmpeg not on PATH)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
