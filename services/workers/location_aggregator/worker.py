"""Presence expiry and retention loops.

Runs the same `PresenceService` code the API uses instead of calling the API
over HTTP, so lease expiry and the purge deadline can never drift from the
request path's behaviour.

Two independent cadences:

* every ``EXPIRE_INTERVAL_SECONDS`` — advance verified → degraded → exited for
  leases whose deadline has passed. Server time is authoritative, so a client
  that goes offline still loses its lease on schedule.
* every ``PURGE_INTERVAL_SECONDS`` — delete location evidence past ``purge_at``.
  Frequent small batches beat one 6:00 AM cron because venues span time zones.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_resources, get_redis, get_session_factory
from app.modules.presence.service import PresenceService

logger = get_logger("location_aggregator")

EXPIRE_INTERVAL_SECONDS = 30
PURGE_INTERVAL_SECONDS = 900
EXPIRE_BATCH_LIMIT = 200
PURGE_BATCH_LIMIT = 5_000
MAX_BATCHES_PER_CYCLE = 20


async def run_expire_cycle(settings: Settings) -> tuple[int, int]:
    """Drain due leases in bounded batches. Returns (degraded, exited)."""
    factory = get_session_factory(settings)
    redis = get_redis(settings)
    degraded = 0
    exited = 0
    async with factory() as session:
        service = PresenceService(session, redis, settings)
        for _ in range(MAX_BATCHES_PER_CYCLE):
            result = await service.expire_batch(limit=EXPIRE_BATCH_LIMIT)
            degraded += result.degraded
            exited += result.exited
            if result.degraded == 0 and result.exited == 0:
                break
    return degraded, exited


async def run_purge_cycle(settings: Settings) -> int:
    factory = get_session_factory(settings)
    redis = get_redis(settings)
    deleted = 0
    async with factory() as session:
        service = PresenceService(session, redis, settings)
        for _ in range(MAX_BATCHES_PER_CYCLE):
            removed = await service.purge_expired_evidence(limit=PURGE_BATCH_LIMIT)
            deleted += removed
            if removed == 0:
                break
    return deleted


async def _loop(
    name: str,
    interval_seconds: int,
    stop: asyncio.Event,
    settings: Settings,
) -> None:
    while not stop.is_set():
        try:
            if name == "expire":
                degraded, exited = await run_expire_cycle(settings)
                if degraded or exited:
                    logger.info("presence_expiry_cycle", degraded=degraded, exited=exited)
            else:
                deleted = await run_purge_cycle(settings)
                if deleted:
                    logger.info("location_evidence_purged", deleted=deleted)
        except Exception as exc:  # noqa: BLE001 - a bad cycle must not kill the worker
            logger.error("aggregator_cycle_failed", cycle=name, error=str(exc))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.app_env != "development")
    logger.info("location_aggregator_starting", app_env=settings.app_env)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    try:
        await asyncio.gather(
            _loop("expire", EXPIRE_INTERVAL_SECONDS, stop, settings),
            _loop("purge", PURGE_INTERVAL_SECONDS, stop, settings),
        )
    finally:
        await dispose_resources()
        logger.info("location_aggregator_stopped")


def main() -> None:
    asyncio.run(_run())
