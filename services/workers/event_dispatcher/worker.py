"""Drain ``app.outbox_events`` via SKIP LOCKED and publish to realtime channels.

Retries use exponential backoff with jitter on ``available_at``. ``published_at``
is set only after the provider acknowledges. Consumers dedupe by event id.

Push fallback: after a successful realtime publish, wait briefly for
``POST /v1/events/{event_id}/ack`` (Valkey ``realtime:ack:{event_id}``). If the
ack is missing, request push for each recipient channel.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import random
import signal
import socket
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.models import OutboxEvent
from app.db.session import dispose_resources, get_redis, get_session_factory
from app.modules.realtime.ack import has_event_ack
from app.modules.realtime.factory import build_push_publisher, build_realtime_publisher
from app.modules.realtime.protocols import PushPublisher, RealtimePublisher

logger = get_logger("event_dispatcher")


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def write_heartbeat(path: Path, *, now: datetime) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=str(path.parent), prefix=".heartbeat-", delete=False
        ) as handle:
            handle.write(now.isoformat())
            temporary = Path(handle.name)
        temporary.replace(path)
    except OSError as exc:
        logger.warning("event_dispatcher_heartbeat_write_failed", error=str(exc))


def heartbeat_is_fresh(path: Path, *, max_age_seconds: int, now: datetime) -> bool:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        stamped = datetime.fromisoformat(raw)
    except (OSError, ValueError):
        return False
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=UTC)
    return (now - stamped).total_seconds() <= max_age_seconds


def _backoff_seconds(attempts: int, base: int) -> float:
    # Exponential with full jitter, capped.
    ceiling = min(base * (2 ** max(attempts - 1, 0)), 300)
    return random.uniform(0, ceiling)


def _channels_for(event: OutboxEvent) -> list[str]:
    payload = event.payload or {}
    recipients = payload.get("recipient_user_ids")
    channels: list[str] = []
    if isinstance(recipients, list):
        for raw in recipients:
            channels.append(f"user:{raw}")
    if not channels:
        # Presence / media events target the subject user when present.
        user_id = payload.get("user_id") or payload.get("blocked_user_id")
        if user_id:
            channels.append(f"user:{user_id}")
        blocker = payload.get("blocker_user_id")
        if blocker:
            channels.append(f"user:{blocker}")
    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for channel in channels:
        if channel not in seen:
            seen.add(channel)
            ordered.append(channel)
    return ordered


async def claim_events(
    session: AsyncSession,
    *,
    limit: int,
    now: datetime,
) -> list[OutboxEvent]:
    result = await session.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.published_at.is_(None),
            OutboxEvent.available_at <= now,
        )
        .order_by(OutboxEvent.available_at, OutboxEvent.occurred_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def _request_push_fallback(
    event: OutboxEvent,
    channels: list[str],
    *,
    push: PushPublisher,
) -> None:
    for channel in channels:
        user_id = channel.removeprefix("user:")
        await push.publish(
            user_id=user_id,
            event_id=str(event.id),
            event_type=event.event_type,
            payload={"aggregate_id": str(event.aggregate_id), "event_type": event.event_type},
        )


async def publish_event(
    event: OutboxEvent,
    *,
    realtime: RealtimePublisher,
    push: PushPublisher,
    redis: Redis[str],
    ack_wait_seconds: float,
) -> None:
    channels = _channels_for(event)
    envelope = {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "event_version": event.event_version,
        "occurred_at": event.occurred_at.isoformat(),
        "aggregate_id": str(event.aggregate_id),
        "trace_id": event.trace_id,
        "payload": event.payload,
    }
    if not channels:
        # Nothing to fan out; still mark published so the row does not stick.
        return

    try:
        for channel in channels:
            await realtime.publish(
                channel,
                event_id=str(event.id),
                event_type=event.event_type,
                payload=envelope,
            )
    except Exception:
        # Realtime unavailable: still attempt push, then re-raise for outbox retry.
        await _request_push_fallback(event, channels, push=push)
        raise

    if ack_wait_seconds > 0:
        await asyncio.sleep(ack_wait_seconds)

    if not await has_event_ack(redis, event_id=str(event.id)):
        logger.info(
            "outbox_push_fallback",
            event_id=str(event.id),
            event_type=event.event_type,
            reason="realtime_ack_missing",
        )
        await _request_push_fallback(event, channels, push=push)


async def run_dispatch_cycle(settings: Settings) -> int:
    factory = get_session_factory(settings)
    realtime = build_realtime_publisher(settings)
    push = build_push_publisher(settings)
    redis = get_redis(settings)
    handled = 0
    now = datetime.now(UTC)

    async with factory() as session:
        events = await claim_events(session, limit=settings.event_dispatcher_batch_size, now=now)
        for event in events:
            try:
                await publish_event(
                    event,
                    realtime=realtime,
                    push=push,
                    redis=redis,
                    ack_wait_seconds=settings.realtime_ack_wait_seconds,
                )
            except Exception as exc:
                event.attempts = int(event.attempts or 0) + 1
                event.last_error = str(exc)[:500]
                delay = _backoff_seconds(
                    event.attempts, settings.event_dispatcher_retry_backoff_seconds
                )
                if event.attempts >= settings.event_dispatcher_max_attempts:
                    # Park far in the future so the row stops thrashing.
                    event.available_at = now + timedelta(days=365)
                    logger.error(
                        "outbox_event_exhausted",
                        event_id=str(event.id),
                        event_type=event.event_type,
                        attempts=event.attempts,
                        error=str(exc),
                    )
                else:
                    event.available_at = now + timedelta(seconds=delay)
                    logger.warning(
                        "outbox_event_retry",
                        event_id=str(event.id),
                        event_type=event.event_type,
                        attempts=event.attempts,
                        retry_in_seconds=round(delay, 2),
                        error=str(exc),
                    )
            else:
                event.published_at = now
                event.last_error = None
                logger.info(
                    "outbox_event_published",
                    event_id=str(event.id),
                    event_type=event.event_type,
                    aggregate_id=str(event.aggregate_id),
                )
            handled += 1
        await session.commit()
    return handled


async def _loop(stop: asyncio.Event, settings: Settings) -> None:
    heartbeat = Path(settings.event_dispatcher_heartbeat_path)
    while not stop.is_set():
        try:
            await run_dispatch_cycle(settings)
        except Exception as exc:
            logger.error("event_dispatcher_cycle_failed", error=str(exc))
        write_heartbeat(heartbeat, now=datetime.now(UTC))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                stop.wait(), timeout=settings.event_dispatcher_poll_interval_seconds
            )


async def _run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.app_env != "development")
    logger.info(
        "event_dispatcher_starting",
        app_env=settings.app_env,
        realtime_provider=settings.realtime_provider,
        push_provider=settings.push_provider,
        worker=worker_identity(),
    )
    write_heartbeat(Path(settings.event_dispatcher_heartbeat_path), now=datetime.now(UTC))

    # Fail fast if Postgres is unreachable.
    factory = get_session_factory(settings)
    async with factory() as session:
        await session.execute(text("SELECT 1"))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    try:
        await _loop(stop, settings)
    finally:
        await dispose_resources()
        logger.info("event_dispatcher_stopped")


def main() -> None:
    asyncio.run(_run())
