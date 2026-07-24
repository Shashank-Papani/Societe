#!/usr/bin/env sh
set -eu

echo "[api] waiting for postgres and valkey..."
python - <<'PY'
import asyncio
import os
import sys
import time

import asyncpg
from redis.asyncio import Redis


async def wait_postgres(url: str, timeout: float = 60.0) -> None:
    # asyncpg wants postgresql:// not postgresql+asyncpg://
    dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            conn = await asyncpg.connect(dsn)
            await conn.close()
            return
        except Exception as exc:  # noqa: BLE001 — bootstrap wait loop
            last = exc
            await asyncio.sleep(1)
    raise SystemExit(f"postgres not ready: {last}")


async def wait_valkey(url: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        client = Redis.from_url(url)
        try:
            if await client.ping():
                await client.aclose()
                return
        except Exception as exc:  # noqa: BLE001
            last = exc
        finally:
            await client.aclose()
        await asyncio.sleep(1)
    raise SystemExit(f"valkey not ready: {last}")


async def main() -> None:
    await wait_postgres(os.environ["DATABASE_URL"])
    await wait_valkey(os.environ["VALKEY_URL"])


asyncio.run(main())
print("[api] dependencies ready")
PY

exec "$@"
