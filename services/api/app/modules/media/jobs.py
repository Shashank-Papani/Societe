"""Durable job queue for the media pipeline.

PostgreSQL rather than a broker: the job row is inserted in the same transaction
that marks an upload accepted, so "accepted but never queued" is not a state the
system can reach. That atomicity is worth more here than queue throughput.

``FOR UPDATE SKIP LOCKED`` lets several workers drain the same table without
coordinating, and a lease timeout returns work abandoned by a crashed worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings

CLAIM_SQL = """
WITH claimed AS (
    SELECT id
    FROM app.media_processing_jobs
    WHERE status IN ('pending', 'failed')
      AND next_attempt_at <= :now
      AND job_type = ANY(:job_types)
    ORDER BY next_attempt_at
    FOR UPDATE SKIP LOCKED
    LIMIT :limit
)
UPDATE app.media_processing_jobs j
SET status = 'leased',
    leased_at = :now,
    lease_owner = :owner,
    attempt_count = j.attempt_count + 1
FROM claimed
WHERE j.id = claimed.id
RETURNING j.id, j.media_asset_id, j.job_type, j.attempt_count
"""

RECLAIM_SQL = """
WITH stale AS (
    SELECT id
    FROM app.media_processing_jobs
    WHERE status = 'leased'
      AND leased_at IS NOT NULL
      AND leased_at <= :cutoff
    ORDER BY leased_at
    FOR UPDATE SKIP LOCKED
    LIMIT :limit
)
UPDATE app.media_processing_jobs j
SET status = 'pending',
    leased_at = NULL,
    lease_owner = NULL,
    next_attempt_at = :now,
    last_error_category = COALESCE(j.last_error_category, 'lease_expired')
FROM stale
WHERE j.id = stale.id
RETURNING j.id
"""


@dataclass(frozen=True)
class ClaimedJob:
    id: UUID
    media_asset_id: UUID
    job_type: str
    attempt_count: int


class MediaJobStore:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def claim(
        self,
        *,
        job_types: list[str],
        owner: str,
        limit: int,
        now: datetime,
    ) -> list[ClaimedJob]:
        result = await self._session.execute(
            text(CLAIM_SQL),
            {"now": now, "job_types": job_types, "limit": limit, "owner": owner},
        )
        rows = result.mappings().all()
        await self._session.commit()
        return [
            ClaimedJob(
                id=row["id"],
                media_asset_id=row["media_asset_id"],
                job_type=row["job_type"],
                attempt_count=int(row["attempt_count"]),
            )
            for row in rows
        ]

    async def reclaim_stale_leases(self, *, now: datetime, limit: int = 50) -> int:
        cutoff = now - timedelta(seconds=self._settings.media_worker_heartbeat_max_age_seconds * 5)
        result = await self._session.execute(
            text(RECLAIM_SQL), {"now": now, "cutoff": cutoff, "limit": limit}
        )
        reclaimed = len(result.mappings().all())
        await self._session.commit()
        return reclaimed

    async def mark_succeeded(self, job_id: UUID, *, now: datetime) -> None:
        await self._session.execute(
            text(
                """
                UPDATE app.media_processing_jobs
                SET status = 'succeeded', completed_at = :now, leased_at = NULL, lease_owner = NULL
                WHERE id = :id
                """
            ),
            {"id": str(job_id), "now": now},
        )
        await self._session.commit()

    async def mark_failed(
        self,
        job_id: UUID,
        *,
        now: datetime,
        attempt_count: int,
        error_category: str,
    ) -> str:
        """Schedule a retry, or dead-letter once attempts are exhausted."""
        exhausted = attempt_count >= self._settings.media_processing_max_attempts
        status = "dead_letter" if exhausted else "failed"
        # Linear backoff keyed to attempt count: a transcode that failed on a
        # transient resource shortage should not hammer ffmpeg immediately.
        delay = self._settings.media_processing_retry_backoff_seconds * attempt_count
        await self._session.execute(
            text(
                """
                UPDATE app.media_processing_jobs
                SET status = :status,
                    last_error_category = :error_category,
                    next_attempt_at = :next_attempt_at,
                    leased_at = NULL,
                    lease_owner = NULL,
                    -- Explicit cast: both CASE branches are parameters or NULL,
                    -- so the driver has nothing to infer a timestamptz from.
                    completed_at = CASE
                        WHEN :status = 'dead_letter' THEN CAST(:now AS timestamptz)
                        ELSE NULL
                    END
                WHERE id = :id
                """
            ),
            {
                "id": str(job_id),
                "status": status,
                "error_category": error_category,
                "next_attempt_at": now + timedelta(seconds=delay),
                "now": now,
            },
        )
        await self._session.commit()
        return status

    async def enqueue(
        self,
        media_asset_id: UUID,
        job_type: str,
        *,
        now: datetime,
        delay_seconds: int = 0,
    ) -> None:
        """Insert without committing: callers batch this into their transaction."""
        await self._session.execute(
            text(
                """
                INSERT INTO app.media_processing_jobs
                    (media_asset_id, job_type, status, next_attempt_at, created_at)
                VALUES (CAST(:media_asset_id AS uuid), :job_type, 'pending', :next_attempt_at, :now)
                """
            ),
            {
                "media_asset_id": str(media_asset_id),
                "job_type": job_type,
                "next_attempt_at": now + timedelta(seconds=delay_seconds),
                "now": now,
            },
        )
