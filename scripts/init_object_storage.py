#!/usr/bin/env python3
"""Create the private quarantine and processed buckets.

Runs as a one-shot Compose service instead of an `mc` container so bucket
creation uses exactly the same adapter and credentials the API uses. Buckets are
created with no public policy: every read is a short-lived signed URL.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "services" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


async def main() -> int:
    from app.core.config import get_settings
    from app.modules.media.storage import build_object_storage

    settings = get_settings()
    storage = build_object_storage(settings)
    await storage.ensure_buckets()
    print(
        "Object storage ready: "
        f"{settings.media_quarantine_bucket}, {settings.media_processed_bucket} "
        f"at {settings.minio_endpoint}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
