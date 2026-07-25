"""Video transcoder port.

Local development and Phase 3 workers use ffmpeg directly. Production will swap
in AWS MediaConvert without changing the pipeline: both implement ``VideoTranscoder``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from app.core.config import Settings
from app.modules.media.processors import ProcessedMedia, VideoPipeline


@runtime_checkable
class VideoTranscoder(Protocol):
    """Normalize a quarantine original into progressive derivatives.

    Implementations must never accept client-supplied command arguments. Output
    is a progressive MP4 plus poster; HLS ladders are a later concern and are
    not required of Phase 3 adapters.
    """

    provider: str

    def available(self) -> bool: ...

    async def process(self, source: Path, workdir: Path) -> ProcessedMedia: ...


class LocalFfmpegTranscoder:
    """Phase 3 local adapter — fixed argv, hard timeout, no network protocols."""

    provider = "ffmpeg"

    def __init__(self, settings: Settings) -> None:
        self._pipeline = VideoPipeline(settings)

    def available(self) -> bool:
        return self._pipeline.available()

    async def process(self, source: Path, workdir: Path) -> ProcessedMedia:
        return await self._pipeline.process(source, workdir)


class MediaConvertTranscoder:
    """Production seam. Not wired in Phase 3 — raises until AWS jobs exist."""

    provider = "mediaconvert"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def available(self) -> bool:
        return False

    async def process(self, source: Path, workdir: Path) -> ProcessedMedia:
        msg = (
            "MediaConvertTranscoder is a Phase-6+ production seam. "
            "Configure LocalFfmpegTranscoder for Phase 3."
        )
        raise NotImplementedError(msg)


def build_video_transcoder(settings: Settings) -> VideoTranscoder:
    """Always local ffmpeg in Phase 3. MediaConvert is selectable later."""
    return LocalFfmpegTranscoder(settings)
