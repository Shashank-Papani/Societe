"""Compose healthcheck: is the worker still completing cycles?

A liveness check on the process alone would report a wedged worker as healthy.
This reads the heartbeat the loops refresh, so "up but stuck" fails.

Usage: ``python -m media_processor.healthcheck``
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from media_processor.worker import heartbeat_is_fresh


def main() -> int:
    settings = get_settings()
    path = Path(settings.media_worker_heartbeat_path)
    fresh = heartbeat_is_fresh(
        path,
        max_age_seconds=settings.media_worker_heartbeat_max_age_seconds,
        now=datetime.now(UTC),
    )
    if not fresh:
        print(f"media-processor heartbeat at {path} is missing or stale", file=sys.stderr)
        return 1
    print("media-processor heartbeat is fresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
