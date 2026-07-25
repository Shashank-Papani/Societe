"""Venue Live Vibe feed, reports, and author deletion.

Reading the feed requires authentication but **not** presence: a user deciding
whether to walk into a bar is not standing in it yet. Posting requires a verified
lease; looking does not.

Only `published` vibes whose window is still open and whose media reached `ready`
are visible. That triple condition is the guard against publishing something the
moderation pipeline has not approved: a vibe row alone is never enough.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import DateTime, func, literal, select, tuple_
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import (
    ContentReport,
    LiveVibe,
    MediaAsset,
    MediaDerivative,
    OutboxEvent,
    User,
)
from app.modules.media.access import may_issue_signed_urls
from app.modules.media.authz import MediaRateLimiter
from app.modules.media.lifecycle import MediaLifecycleService, VibeLifecycleService
from app.modules.media.schemas import (
    CreateReportRequest,
    CreateReportResponse,
    CreatorVibeItem,
    CreatorVibeListResponse,
    DeleteVibeResponse,
    VibeAuthor,
    VibeFeedItem,
    VibeFeedResponse,
)
from app.modules.media.storage import ObjectStorage, build_object_storage
from app.modules.media.urls import build_signed_variants
from app.shared.cursors import keyset_fingerprint, sign_keyset_cursor, verify_keyset_cursor

logger = get_logger(__name__)

FEED_NAME = "venue_live_vibes"

#: A vibe is reportable while it is (or was recently) visible.
REPORTABLE_STATUSES = frozenset({"published", "hidden"})


@dataclass(frozen=True)
class FeedRow:
    vibe: LiveVibe
    asset: MediaAsset
    author: User


class VibeService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis[str],
        settings: Settings,
        storage: ObjectStorage | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._storage = storage or build_object_storage(settings)
        self._limits = MediaRateLimiter(redis, settings)
        self._media_lifecycle = MediaLifecycleService()
        self._vibe_lifecycle = VibeLifecycleService(settings)

    # -------------------------------------------------------------------- feed

    async def venue_feed(
        self,
        *,
        venue_id: UUID,
        viewer: User,
        cursor: str | None,
        limit: int,
        now: datetime,
    ) -> VibeFeedResponse:
        qfp = keyset_fingerprint(feed=FEED_NAME, venue_id=str(venue_id))
        stmt = (
            select(LiveVibe, MediaAsset, User)
            .join(MediaAsset, MediaAsset.id == LiveVibe.media_asset_id)
            .join(User, User.id == LiveVibe.author_user_id)
            .where(
                LiveVibe.venue_id == venue_id,
                LiveVibe.publication_status == "published",
                LiveVibe.published_at.is_not(None),
                LiveVibe.expires_at.is_not(None),
                LiveVibe.expires_at > now,
                # Publication and readiness are tracked separately; require both
                # so a vibe row can never outrun its moderated media.
                MediaAsset.lifecycle_status == "ready",
                MediaAsset.moderation_status == "approved",
                MediaAsset.deleted_at.is_(None),
                User.deleted_at.is_(None),
                User.account_status == "active",
            )
            .order_by(LiveVibe.published_at.desc(), LiveVibe.id.desc())
            .limit(limit + 1)
        )
        if cursor:
            payload = verify_keyset_cursor(
                cursor=cursor,
                expected_qfp=qfp,
                secret=self._settings.cursor_hmac_secret.get_secret_value(),
            )
            # Row-value comparison, so the keyset stays a single index seek. The
            # bounds are typed literals because the driver cannot infer a
            # timestamptz or a uuid from a bare parameter inside a row value.
            stmt = stmt.where(
                tuple_(LiveVibe.published_at, LiveVibe.id)
                < tuple_(
                    literal(
                        datetime.fromisoformat(str(payload["sk"])),
                        DateTime(timezone=True),
                    ),
                    literal(UUID(str(payload["id"])), PostgresUUID(as_uuid=True)),
                )
            )

        result = await self._session.execute(stmt)
        rows = [FeedRow(vibe=v, asset=a, author=u) for v, a, u in result.all()]
        page = rows[:limit]
        has_more = len(rows) > limit

        derivatives = await self._derivatives_for(page)
        items: list[VibeFeedItem] = []
        for row in page:
            # Public feed never mints URLs for revoked/deleted rows; those are
            # already filtered out. Still gate on the shared policy so a future
            # soft-expire race cannot leak a fresh signature.
            if may_issue_signed_urls(
                row.asset, row.vibe, now=now, settings=self._settings, creator_view=False
            ):
                variants = await build_signed_variants(
                    self._storage,
                    self._settings,
                    derivatives.get(row.asset.id, []),
                    now=now,
                )
            else:
                variants = []
            anonymous = row.vibe.attribution_mode == "anonymous"
            items.append(
                VibeFeedItem(
                    id=row.vibe.id,
                    venue_id=row.vibe.venue_id,
                    media_type=row.asset.media_type,  # type: ignore[arg-type]
                    attribution_mode=row.vibe.attribution_mode,  # type: ignore[arg-type]
                    # An anonymous post carries no identifier at all: an author id
                    # would be enough to correlate posts back to one person.
                    author=(
                        None
                        if anonymous
                        else VibeAuthor(
                            id=row.author.id,
                            handle=row.author.handle,
                            display_name=row.author.display_name,
                        )
                    ),
                    author_label="Anonymous" if anonymous else row.author.display_name,
                    caption=row.vibe.caption,
                    vibe_tags=list(row.vibe.vibe_tags or []),
                    published_at=_require(row.vibe.published_at),
                    expires_at=_require(row.vibe.expires_at),
                    variants=variants,
                    viewer_is_author=row.vibe.author_user_id == viewer.id,
                )
            )

        next_cursor: str | None = None
        if has_more and page:
            last = page[-1]
            next_cursor = sign_keyset_cursor(
                sort_key=_require(last.vibe.published_at).isoformat(),
                item_id=str(last.vibe.id),
                qfp=qfp,
                secret=self._settings.cursor_hmac_secret.get_secret_value(),
                ttl_seconds=self._settings.cursor_ttl_seconds,
            )
        return VibeFeedResponse(items=items, next_cursor=next_cursor)

    async def creator_vibes(
        self,
        *,
        author: User,
        cursor: str | None,
        limit: int,
        now: datetime,
    ) -> CreatorVibeListResponse:
        """Author-facing history: includes expired metadata, gated media URLs."""
        qfp = keyset_fingerprint(feed="creator_live_vibes", author_id=str(author.id))
        stmt = (
            select(LiveVibe, MediaAsset)
            .join(MediaAsset, MediaAsset.id == LiveVibe.media_asset_id)
            .where(
                LiveVibe.author_user_id == author.id,
                LiveVibe.publication_status.notin_(("deleted",)),
            )
            .order_by(LiveVibe.created_at.desc(), LiveVibe.id.desc())
            .limit(limit + 1)
        )
        if cursor:
            payload = verify_keyset_cursor(
                cursor=cursor,
                expected_qfp=qfp,
                secret=self._settings.cursor_hmac_secret.get_secret_value(),
            )
            stmt = stmt.where(
                tuple_(LiveVibe.created_at, LiveVibe.id)
                < tuple_(
                    literal(
                        datetime.fromisoformat(str(payload["sk"])),
                        DateTime(timezone=True),
                    ),
                    literal(UUID(str(payload["id"])), PostgresUUID(as_uuid=True)),
                )
            )

        result = await self._session.execute(stmt)
        rows = [(v, a) for v, a in result.all()]
        page = rows[:limit]
        has_more = len(rows) > limit

        feed_rows = [FeedRow(vibe=v, asset=a, author=author) for v, a in page]
        derivatives = await self._derivatives_for(feed_rows)
        items: list[CreatorVibeItem] = []
        for vibe, asset in page:
            if may_issue_signed_urls(
                asset, vibe, now=now, settings=self._settings, creator_view=True
            ):
                variants = await build_signed_variants(
                    self._storage,
                    self._settings,
                    derivatives.get(asset.id, []),
                    now=now,
                )
            else:
                variants = []
            items.append(
                CreatorVibeItem(
                    id=vibe.id,
                    venue_id=vibe.venue_id,
                    media_asset_id=asset.id,
                    media_type=asset.media_type,
                    attribution_mode=vibe.attribution_mode,
                    publication_status=vibe.publication_status,
                    lifecycle_status=asset.lifecycle_status,
                    moderation_status=asset.moderation_status,
                    caption=vibe.caption,
                    vibe_tags=list(vibe.vibe_tags or []),
                    created_at=vibe.created_at,
                    published_at=vibe.published_at,
                    expires_at=vibe.expires_at,
                    variants=variants,
                )
            )

        next_cursor: str | None = None
        if has_more and page:
            last_vibe, _ = page[-1]
            next_cursor = sign_keyset_cursor(
                sort_key=last_vibe.created_at.isoformat(),
                item_id=str(last_vibe.id),
                qfp=qfp,
                secret=self._settings.cursor_hmac_secret.get_secret_value(),
                ttl_seconds=self._settings.cursor_ttl_seconds,
            )
        return CreatorVibeListResponse(items=items, next_cursor=next_cursor)

    async def _derivatives_for(self, rows: list[FeedRow]) -> dict[UUID, list[MediaDerivative]]:
        if not rows:
            return {}
        generations = {row.asset.id: row.asset.generation for row in rows}
        result = await self._session.execute(
            select(MediaDerivative).where(
                MediaDerivative.media_asset_id.in_(list(generations)),
                MediaDerivative.status == "ready",
            )
        )
        grouped: dict[UUID, list[MediaDerivative]] = {}
        for derivative in result.scalars().all():
            if derivative.generation != generations.get(derivative.media_asset_id):
                continue
            grouped.setdefault(derivative.media_asset_id, []).append(derivative)
        return grouped

    # ----------------------------------------------------------------- reports

    async def report(
        self,
        *,
        reporter: User,
        vibe_id: UUID,
        request: CreateReportRequest,
        now: datetime,
    ) -> CreateReportResponse:
        max_length = self._settings.vibe_report_description_max_length
        if request.description is not None and len(request.description) > max_length:
            raise AppError(
                "REPORT_DESCRIPTION_TOO_LONG",
                f"Report description exceeds {max_length} characters.",
                status_code=400,
                details={"max_length": max_length},
            )

        vibe = await self._load_vibe(vibe_id, for_update=True)
        if vibe.publication_status not in REPORTABLE_STATUSES:
            raise AppError("VIBE_NOT_FOUND", "Live Vibe not found.", status_code=404)
        if vibe.author_user_id == reporter.id:
            raise AppError(
                "CANNOT_REPORT_OWN_CONTENT",
                "You cannot report your own Live Vibe.",
                status_code=400,
            )

        await self._limits.check_report(user_id=reporter.id, now=now)

        report = ContentReport(
            reporter_user_id=reporter.id,
            live_vibe_id=vibe.id,
            reason=request.reason,
            description=request.description,
            status="open",
            created_at=now,
        )
        self._session.add(report)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise AppError(
                "REPORT_ALREADY_SUBMITTED",
                "You already reported this Live Vibe.",
                status_code=409,
            ) from exc

        hidden = await self._maybe_auto_hide(vibe, now=now)
        self._session.add(
            OutboxEvent(
                aggregate_type="live_vibe",
                aggregate_id=vibe.id,
                event_type="content.reported",
                payload={
                    "live_vibe_id": str(vibe.id),
                    "media_asset_id": str(vibe.media_asset_id),
                    "venue_id": str(vibe.venue_id),
                    "reason": request.reason,
                    "auto_hidden": hidden,
                    "reported_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()
        logger.info(
            "vibe_reported",
            live_vibe_id=str(vibe.id),
            reason=request.reason,
            auto_hidden=hidden,
        )
        return CreateReportResponse(
            report_id=report.id,
            live_vibe_id=vibe.id,
            reason=request.reason,
            status="open",
            created_at=now,
            content_hidden=hidden,
        )

    async def _maybe_auto_hide(self, vibe: LiveVibe, *, now: datetime) -> bool:
        """Hide only when an explicit policy threshold is configured and met.

        The default is disabled. A single report must not be a takedown button:
        one motivated user could otherwise clear a venue's feed.
        """
        threshold = self._settings.vibe_report_auto_hide_threshold
        if threshold <= 0 or vibe.publication_status != "published":
            return False
        result = await self._session.execute(
            select(func.count())
            .select_from(ContentReport)
            .where(
                ContentReport.live_vibe_id == vibe.id,
                ContentReport.status.in_(("open", "triaged")),
            )
        )
        if int(result.scalar_one()) < threshold:
            return False
        self._vibe_lifecycle.hide(vibe, now=now, reason="report_threshold")
        return True

    # ------------------------------------------------------------------ delete

    async def delete(self, *, user: User, vibe_id: UUID, now: datetime) -> DeleteVibeResponse:
        vibe = await self._load_vibe(vibe_id, for_update=True)
        if vibe.author_user_id != user.id:
            raise AppError("VIBE_NOT_FOUND", "Live Vibe not found.", status_code=404)

        self._vibe_lifecycle.delete(vibe, now=now, reason="author_deleted")
        result = await self._session.execute(
            select(MediaAsset).where(MediaAsset.id == vibe.media_asset_id).with_for_update()
        )
        asset = result.scalar_one_or_none()
        if asset is not None and asset.lifecycle_status != "deleted":
            self._media_lifecycle.mark_deleted(asset, now=now, reason="author_deleted")
        self._session.add(
            OutboxEvent(
                aggregate_type="live_vibe",
                aggregate_id=vibe.id,
                event_type="live_vibe.deleted",
                payload={
                    "live_vibe_id": str(vibe.id),
                    "venue_id": str(vibe.venue_id),
                    "media_asset_id": str(vibe.media_asset_id),
                    "deleted_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()
        return DeleteVibeResponse(
            live_vibe_id=vibe.id,
            publication_status=vibe.publication_status,  # type: ignore[arg-type]
        )

    async def _load_vibe(self, vibe_id: UUID, *, for_update: bool = False) -> LiveVibe:
        stmt = select(LiveVibe).where(LiveVibe.id == vibe_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        vibe = result.scalar_one_or_none()
        if vibe is None or vibe.publication_status == "deleted":
            raise AppError("VIBE_NOT_FOUND", "Live Vibe not found.", status_code=404)
        return vibe


def _require(value: datetime | None) -> datetime:
    # The feed query filters these to NOT NULL; this keeps the type checker honest.
    assert value is not None
    return value
