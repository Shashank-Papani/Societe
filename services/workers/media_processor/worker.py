"""Media processing, moderation, expiry, and retention loops.

One binary, several job types. Splitting validation and moderation into separate
deployments buys nothing here: both need the same ffmpeg/Pillow image and the
same object storage credentials, and a combined worker keeps a single place where
the pipeline's ordering is expressed.

The worker imports the same ``MediaPipeline`` the API and tests use rather than
calling the API over HTTP, so a status transition cannot drift between the
request path and the background path.

Two cadences:

* every ``MEDIA_WORKER_POLL_INTERVAL_SECONDS`` — claim and run pipeline jobs with
  ``FOR UPDATE SKIP LOCKED``, so several replicas can drain the queue without
  coordinating.
* every ``RETENTION_INTERVAL_SECONDS`` — expire published vibes, close abandoned
  intents, and delete objects past their retention window. Venues span time
  zones, so this cannot be a nightly cron.

A heartbeat file is refreshed on every pass of each loop. The Compose
healthcheck reads it, which makes a wedged cycle visible instead of leaving a
process that is "up" and doing nothing.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_resources, get_redis, get_session_factory
from app.modules.media.jobs import MediaJobStore
from app.modules.media.pipeline import MediaPipeline
from app.modules.media.retention import MediaRetentionService, RetentionResult
from app.modules.media.service import MediaService
from app.modules.media.storage import build_object_storage

logger = get_logger("media_processor")

JOB_TYPES = ["validate_process", "moderate"]
RETENTION_INTERVAL_SECONDS = 300
INTENT_EXPIRY_BATCH = 200
MAX_CYCLES_PER_PASS = 10


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def write_heartbeat(path: Path, *, now: datetime) -> None:
    """Atomic-ish write so a healthcheck never reads a half-written file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=str(path.parent), prefix=".heartbeat-", delete=False
        ) as handle:
            handle.write(now.isoformat())
            temporary = Path(handle.name)
        temporary.replace(path)
    except OSError as exc:
        logger.warning("media_worker_heartbeat_write_failed", error=str(exc))


def heartbeat_is_fresh(path: Path, *, max_age_seconds: int, now: datetime) -> bool:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        stamped = datetime.fromisoformat(raw)
    except (OSError, ValueError):
        return False
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=UTC)
    return (now - stamped).total_seconds() <= max_age_seconds


async def run_job_cycle(settings: Settings) -> int:
    """Claim and run one batch of pipeline jobs. Returns jobs handled."""
    factory = get_session_factory(settings)
    storage = build_object_storage(settings)
    owner = worker_identity()
    handled = 0

    async with factory() as session:
        jobs = MediaJobStore(session, settings)
        await jobs.reclaim_stale_leases(now=datetime.now(UTC))
        claimed = await jobs.claim(
            job_types=JOB_TYPES,
            owner=owner,
            limit=settings.media_worker_batch_size,
            now=datetime.now(UTC),
        )

    for job in claimed:
        async with factory() as session:
            store = MediaJobStore(session, settings)
            pipeline = MediaPipeline(session, settings, storage=storage)
            try:
                outcome = await pipeline.run(job, now=datetime.now(UTC))
            except Exception as exc:
                await session.rollback()
                logger.error(
                    "media_job_crashed",
                    job_id=str(job.id),
                    job_type=job.job_type,
                    media_asset_id=str(job.media_asset_id),
                    error=str(exc),
                )
                await store.mark_failed(
                    job.id,
                    now=datetime.now(UTC),
                    attempt_count=job.attempt_count,
                    error_category="unhandled_exception",
                )
                handled += 1
                continue

            if outcome.should_retry:
                status = await store.mark_failed(
                    job.id,
                    now=datetime.now(UTC),
                    attempt_count=job.attempt_count,
                    error_category=outcome.detail or "retry",
                )
                logger.warning(
                    "media_job_retry_scheduled",
                    job_id=str(job.id),
                    job_type=job.job_type,
                    status=status,
                    reason=outcome.detail,
                )
            else:
                await store.mark_succeeded(job.id, now=datetime.now(UTC))
                logger.info(
                    "media_job_finished",
                    job_id=str(job.id),
                    job_type=job.job_type,
                    outcome=outcome.status,
                    detail=outcome.detail,
                )
            handled += 1
    return handled


async def run_retention_cycle(settings: Settings) -> tuple[RetentionResult, int]:
    factory = get_session_factory(settings)
    storage = build_object_storage(settings)
    redis = get_redis(settings)
    now = datetime.now(UTC)

    async with factory() as session:
        retention = MediaRetentionService(session, settings, storage)
        result = await retention.run_all(now=now)

    async with factory() as session:
        media = MediaService(session, redis, settings, storage)
        expired_intents = await media.expire_abandoned_intents(now=now, limit=INTENT_EXPIRY_BATCH)

    return result, expired_intents


async def _loop(name: str, interval_seconds: int, stop: asyncio.Event, settings: Settings) -> None:
    heartbeat = Path(settings.media_worker_heartbeat_path)
    while not stop.is_set():
        try:
            if name == "jobs":
                for _ in range(MAX_CYCLES_PER_PASS):
                    if await run_job_cycle(settings) == 0:
                        break
            else:
                result, expired_intents = await run_retention_cycle(settings)
                if result.total or expired_intents:
                    logger.info(
                        "media_retention_cycle",
                        expired_vibes=result.expired_vibes,
                        expired_intents=expired_intents,
                        incomplete_uploads_purged=result.incomplete_uploads_purged,
                        processed_originals_purged=result.processed_originals_purged,
                        rejected_originals_purged=result.rejected_originals_purged,
                        derivative_sets_purged=result.derivative_sets_purged,
                    )
        except Exception as exc:
            logger.error("media_worker_cycle_failed", cycle=name, error=str(exc))
        # Written even after a failed cycle: the process is alive and looping. A
        # persistently failing cycle is an alert, not a restart signal.
        write_heartbeat(heartbeat, now=datetime.now(UTC))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.app_env != "development")
    logger.info(
        "media_processor_starting",
        app_env=settings.app_env,
        malware_scanner=settings.media_malware_scanner,
        moderation_provider=settings.media_moderation_provider,
        worker=worker_identity(),
    )

    # Fail fast if buckets are missing: a worker that cannot read quarantine will
    # otherwise burn every job's retry budget one download at a time.
    await build_object_storage(settings).ensure_buckets()
    write_heartbeat(Path(settings.media_worker_heartbeat_path), now=datetime.now(UTC))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    try:
        await asyncio.gather(
            _loop("jobs", settings.media_worker_poll_interval_seconds, stop, settings),
            _loop("retention", RETENTION_INTERVAL_SECONDS, stop, settings),
        )
    finally:
        await dispose_resources()
        logger.info("media_processor_stopped")


def main() -> None:
    asyncio.run(_run())
