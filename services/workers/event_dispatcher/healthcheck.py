"""Compose healthcheck: is the dispatcher still completing cycles?"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from event_dispatcher.worker import heartbeat_is_fresh


def main() -> int:
    settings = get_settings()
    path = Path(settings.event_dispatcher_heartbeat_path)
    fresh = heartbeat_is_fresh(
        path,
        max_age_seconds=settings.event_dispatcher_heartbeat_max_age_seconds,
        now=datetime.now(UTC),
    )
    if not fresh:
        print(f"event-dispatcher heartbeat at {path} is missing or stale", file=sys.stderr)
        return 1
    print("event-dispatcher heartbeat is fresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
