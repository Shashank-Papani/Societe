"""User and official venue Stories: upload, grouping, views, reports, deletion."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import (
    MediaAsset,
    MediaDerivative,
    MediaProcessingJob,
    OutboxEvent,
    Story,
    StoryReport,
    StoryView,
    User,
    Venue,
    VenueOrganization,
)
from app.modules.media.access import may_issue_content_signed_urls
from app.modules.media.authz import (
    RETRYABLE_PRESENCE_REASONS,
    validate_declared_media,
)
from app.modules.media.lifecycle import MediaLifecycleService
from app.modules.media.schemas import CreateUploadRequest, MediaVariant
from app.modules.media.storage import ObjectStorage, build_object_storage, quarantine_object_key
from app.modules.media.urls import build_signed_variants
from app.modules.organizations.audit import (
    OFFICIAL_STORY_CREATED,
    OFFICIAL_STORY_DELETED,
    append_audit_event,
)
from app.modules.organizations.authz import (
    ACTIVE_VENUE_LINK,
    OrganizationAuthorizer,
    OrgPermission,
)
from app.modules.presence.service import PresenceService
from app.modules.stories.grouping import (
    logical_group_id,
    sign_group_key,
    verify_group_key,
)
from app.modules.stories.lifecycle import (
    STORY_PUBLIC_WINDOW,
    is_publicly_viewable,
    mark_deleted,
    start_processing,
)
from app.modules.stories.publication import publish_content_for_media_asset
from app.modules.stories.rates import StoryRateLimiter
from app.modules.stories.schemas import (
    CompleteStoryUploadRequest,
    CreateOfficialStoryUploadRequest,
    CreateStoryReportRequest,
    CreateStoryReportResponse,
    CreateUserStoryUploadRequest,
    DeleteStoryResponse,
    RecordStoryViewResponse,
    StoryAuthorProjection,
    StoryGroupDetail,
    StoryGroupListResponse,
    StoryGroupSummary,
    StorySlide,
    StoryUploadResponse,
    UploadInstruction,
    VenueStoryProjection,
)

logger = get_logger(__name__)

FAILURE_STATUSES = frozenset(
    {"invalid", "processing_failed", "rejected", "upload_expired", "revoked"}
)
EXPERIENCE_STORY_LIMIT = 200


def require_stories_enabled(settings: Settings) -> None:
    if not settings.ff_stories:
        raise AppError(
            "STORIES_DISABLED",
            "Stories are not enabled.",
            status_code=403,
        )


class StoryService:
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
        self._presence = PresenceService(session, redis, settings)
        self._limits = StoryRateLimiter(redis, settings)
        self._authz = OrganizationAuthorizer(session)
        self._media_lifecycle = MediaLifecycleService()
        self._story_ttl = timedelta(hours=settings.story_ttl_hours)

    # ----------------------------------------------------------- user upload

    async def create_user_story_upload(
        self,
        *,
        user: User,
        request: CreateUserStoryUploadRequest,
        now: datetime,
    ) -> StoryUploadResponse:
        require_stories_enabled(self._settings)
        self._assert_user_eligible(user)

        # Reuse Live Vibe declared-media validation (MIME/size/caption/tags).
        validate_declared_media(
            CreateUploadRequest(
                venue_id=request.venue_id,
                device_id=request.device_id,
                media_type=request.media_type,
                mime_type=request.mime_type,
                byte_size=request.byte_size,
                caption=request.caption,
                vibe_tags=list(request.vibe_tags),
                checksum_sha256=request.checksum_sha256,
            ),
            self._settings,
        )

        device = await self._presence.load_owned_device(user, request.device_id)
        decision = await self._presence.can_post_live_vibe(user, request.venue_id, device, now=now)
        if not decision.allowed or decision.check_in_id is None or decision.venue_id is None:
            reason = decision.reason or "presence_refresh_required"
            raise AppError(
                "STORY_POSTING_NOT_AUTHORIZED",
                "A verified check-in at this venue is required to post a Story.",
                status_code=403,
                details={"reason": reason, "retryable": reason in RETRYABLE_PRESENCE_REASONS},
            )

        await self._limits.check_user_story_intent(user_id=user.id, now=now)

        attribution = request.attribution_mode
        if decision.attribution_mode == "anonymous":
            attribution = "anonymous"

        asset_id = uuid4()
        story_id = uuid4()
        object_key = quarantine_object_key(
            owner_user_id=user.id, asset_id=asset_id, mime_type=request.mime_type
        )
        intent_expires_at = now + timedelta(seconds=self._settings.media_upload_intent_ttl_seconds)

        asset = MediaAsset(
            id=asset_id,
            owner_user_id=user.id,
            venue_id=decision.venue_id,
            purpose="user_story",
            organization_id=None,
            author_check_in_id=decision.check_in_id,
            device_id=device.id,
            media_type=request.media_type,
            lifecycle_status="intent_pending",
            moderation_status="pending",
            attribution_mode=attribution,
            quarantine_object_key=object_key,
            declared_mime_type=request.mime_type,
            declared_byte_size=request.byte_size,
            caption=request.caption,
            vibe_tags=list(request.vibe_tags),
            intent_expires_at=intent_expires_at,
            generation=1,
            moderation_summary=(
                {"declared_checksum_sha256": request.checksum_sha256}
                if request.checksum_sha256
                else {}
            ),
            created_at=now,
        )
        story = Story(
            id=story_id,
            venue_id=decision.venue_id,
            media_asset_id=asset_id,
            author_type="user",
            author_user_id=user.id,
            organization_id=None,
            created_by_user_id=user.id,
            attribution_mode=attribution,
            caption=request.caption,
            vibe_tags=list(request.vibe_tags),
            reply_policy=request.reply_policy,
            publication_status="draft",
            moderation_status="pending",
            created_at=now,
            updated_at=now,
        )
        self._session.add(asset)
        await self._session.flush()
        self._session.add(story)
        self._session.add(
            OutboxEvent(
                aggregate_type="story",
                aggregate_id=story_id,
                event_type="story.upload.created",
                payload={
                    "story_id": str(story_id),
                    "media_asset_id": str(asset_id),
                    "venue_id": str(decision.venue_id),
                    "author_type": "user",
                    "occurred_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()

        upload = await self._storage.presign_put(
            bucket=self._settings.media_quarantine_bucket,
            key=object_key,
            content_type=request.mime_type,
            expires_in=self._settings.media_presigned_put_ttl_seconds,
        )
        logger.info(
            "story_upload_intent_created",
            story_id=str(story_id),
            media_asset_id=str(asset_id),
            venue_id=str(decision.venue_id),
        )
        return StoryUploadResponse(
            story_id=story_id,
            upload_id=asset_id,
            media_asset_id=asset_id,
            lifecycle_status="intent_pending",
            publication_status="draft",
            moderation_status="pending",
            attribution_mode=attribution,
            intent_expires_at=intent_expires_at,
            max_byte_size=request.byte_size,
            upload=UploadInstruction(
                method="PUT",
                url=upload.url,
                headers=upload.headers,
                expires_at=min(upload.expires_at, intent_expires_at),
            ),
        )

    async def complete_user_story_upload(
        self,
        *,
        user: User,
        upload_id: UUID,
        request: CompleteStoryUploadRequest,
        now: datetime,
    ) -> StoryUploadResponse:
        require_stories_enabled(self._settings)
        if request.device_id is None:
            raise AppError(
                "MEDIA_DEVICE_MISMATCH",
                "device_id is required to complete a user Story upload.",
                status_code=400,
            )

        asset = await self._load_owned_story_asset(
            user, upload_id, purpose="user_story", for_update=True
        )
        story = await self._load_story_for_asset(asset.id, for_update=True)

        if request.device_id != asset.device_id:
            raise AppError(
                "MEDIA_DEVICE_MISMATCH",
                "Complete the upload from the device that created it.",
                status_code=403,
            )
        device = await self._presence.load_owned_device(user, request.device_id)

        if asset.intent_consumed_at is not None or asset.lifecycle_status != "intent_pending":
            if asset.lifecycle_status == "intent_pending":
                raise AppError(
                    "MEDIA_UPLOAD_ALREADY_COMPLETED",
                    "This upload was already completed.",
                    status_code=409,
                )
            if asset.lifecycle_status == "upload_expired":
                raise AppError(
                    "STORY_UPLOAD_EXPIRED",
                    "The upload window expired. Start a new upload.",
                    status_code=409,
                )
            return await self._build_upload_status(asset, story, now=now)

        if now >= asset.intent_expires_at:
            self._media_lifecycle.mark_intent_expired(asset, now=now)
            await self._session.commit()
            raise AppError(
                "STORY_UPLOAD_EXPIRED",
                "The upload window expired. Start a new upload.",
                status_code=409,
            )

        decision = await self._presence.can_post_live_vibe(user, asset.venue_id, device, now=now)
        if not decision.allowed:
            raise AppError(
                "STORY_POSTING_NOT_AUTHORIZED",
                "A verified check-in at this venue is required to finish the upload.",
                status_code=403,
                details={"reason": decision.reason or "presence_refresh_required"},
            )

        await self._admit_uploaded_object(asset, request=request, now=now)
        start_processing(story, now=now)
        self._session.add(
            MediaProcessingJob(
                media_asset_id=asset.id,
                job_type="validate_process",
                status="pending",
                next_attempt_at=now,
                created_at=now,
            )
        )
        self._session.add(
            OutboxEvent(
                aggregate_type="story",
                aggregate_id=story.id,
                event_type="story.upload.completed",
                payload={
                    "story_id": str(story.id),
                    "media_asset_id": str(asset.id),
                    "venue_id": str(asset.venue_id),
                    "occurred_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()
        return await self._build_upload_status(asset, story, now=now)

    # ------------------------------------------------------- official upload

    async def create_official_story_upload(
        self,
        *,
        user: User,
        venue_id: UUID,
        request: CreateOfficialStoryUploadRequest,
        now: datetime,
    ) -> StoryUploadResponse:
        require_stories_enabled(self._settings)
        ctx = await self._authz.require_venue_permission(
            user, venue_id, OrgPermission.VENUE_CONTENT_PUBLISH
        )
        validate_declared_media(
            CreateUploadRequest(
                venue_id=venue_id,
                device_id=uuid4(),
                media_type=request.media_type,
                mime_type=request.mime_type,
                byte_size=request.byte_size,
                caption=request.caption,
                vibe_tags=list(request.vibe_tags),
                checksum_sha256=request.checksum_sha256,
            ),
            self._settings,
        )
        await self._limits.check_official_story_intent(organization_id=ctx.organization.id, now=now)

        org_id = ctx.organization.id
        asset_id = uuid4()
        story_id = uuid4()
        object_key = quarantine_object_key(
            owner_user_id=user.id, asset_id=asset_id, mime_type=request.mime_type
        )
        intent_expires_at = now + timedelta(seconds=self._settings.media_upload_intent_ttl_seconds)

        asset = MediaAsset(
            id=asset_id,
            owner_user_id=user.id,
            venue_id=venue_id,
            purpose="venue_owned",
            organization_id=org_id,
            author_check_in_id=None,
            device_id=None,
            media_type=request.media_type,
            lifecycle_status="intent_pending",
            moderation_status="pending",
            # media_assets CHECK only allows attributed|anonymous; Story carries official.
            attribution_mode="attributed",
            quarantine_object_key=object_key,
            declared_mime_type=request.mime_type,
            declared_byte_size=request.byte_size,
            caption=request.caption,
            vibe_tags=list(request.vibe_tags),
            intent_expires_at=intent_expires_at,
            generation=1,
            moderation_summary=(
                {"declared_checksum_sha256": request.checksum_sha256}
                if request.checksum_sha256
                else {}
            ),
            created_at=now,
        )
        story = Story(
            id=story_id,
            venue_id=venue_id,
            media_asset_id=asset_id,
            author_type="venue",
            author_user_id=None,
            organization_id=org_id,
            created_by_user_id=user.id,
            attribution_mode="official",
            caption=request.caption,
            vibe_tags=list(request.vibe_tags),
            reply_policy=request.reply_policy,
            publication_status="draft",
            moderation_status="pending",
            created_at=now,
            updated_at=now,
        )
        self._session.add(asset)
        await self._session.flush()
        self._session.add(story)
        await append_audit_event(
            self._session,
            event_type=OFFICIAL_STORY_CREATED,
            actor_user_id=user.id,
            organization_id=org_id,
            venue_id=venue_id,
            target_type="story",
            target_id=story_id,
            metadata={"story_id": str(story_id), "media_asset_id": str(asset_id)},
        )
        self._session.add(
            OutboxEvent(
                aggregate_type="story",
                aggregate_id=story_id,
                event_type="story.upload.created",
                payload={
                    "story_id": str(story_id),
                    "media_asset_id": str(asset_id),
                    "venue_id": str(venue_id),
                    "author_type": "venue",
                    "organization_id": str(org_id),
                    "occurred_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()

        upload = await self._storage.presign_put(
            bucket=self._settings.media_quarantine_bucket,
            key=object_key,
            content_type=request.mime_type,
            expires_in=self._settings.media_presigned_put_ttl_seconds,
        )
        return StoryUploadResponse(
            story_id=story_id,
            upload_id=asset_id,
            media_asset_id=asset_id,
            lifecycle_status="intent_pending",
            publication_status="draft",
            moderation_status="pending",
            attribution_mode="official",
            intent_expires_at=intent_expires_at,
            max_byte_size=request.byte_size,
            upload=UploadInstruction(
                method="PUT",
                url=upload.url,
                headers=upload.headers,
                expires_at=min(upload.expires_at, intent_expires_at),
            ),
        )

    async def complete_official_story_upload(
        self,
        *,
        user: User,
        upload_id: UUID,
        request: CompleteStoryUploadRequest,
        now: datetime,
    ) -> StoryUploadResponse:
        require_stories_enabled(self._settings)
        asset = await self._load_owned_story_asset(
            user, upload_id, purpose="venue_owned", for_update=True
        )
        story = await self._load_story_for_asset(asset.id, for_update=True)
        if story.author_type != "venue":
            raise AppError("STORY_NOT_FOUND", "Story upload not found.", status_code=404)

        await self._authz.require_venue_permission(
            user, story.venue_id, OrgPermission.VENUE_CONTENT_PUBLISH
        )

        if asset.intent_consumed_at is not None or asset.lifecycle_status != "intent_pending":
            if asset.lifecycle_status == "intent_pending":
                raise AppError(
                    "MEDIA_UPLOAD_ALREADY_COMPLETED",
                    "This upload was already completed.",
                    status_code=409,
                )
            if asset.lifecycle_status == "upload_expired":
                raise AppError(
                    "STORY_UPLOAD_EXPIRED",
                    "The upload window expired. Start a new upload.",
                    status_code=409,
                )
            return await self._build_upload_status(asset, story, now=now)

        if now >= asset.intent_expires_at:
            self._media_lifecycle.mark_intent_expired(asset, now=now)
            await self._session.commit()
            raise AppError(
                "STORY_UPLOAD_EXPIRED",
                "The upload window expired. Start a new upload.",
                status_code=409,
            )

        await self._admit_uploaded_object(asset, request=request, now=now)
        start_processing(story, now=now)
        self._session.add(
            MediaProcessingJob(
                media_asset_id=asset.id,
                job_type="validate_process",
                status="pending",
                next_attempt_at=now,
                created_at=now,
            )
        )
        self._session.add(
            OutboxEvent(
                aggregate_type="story",
                aggregate_id=story.id,
                event_type="story.upload.completed",
                payload={
                    "story_id": str(story.id),
                    "media_asset_id": str(asset.id),
                    "venue_id": str(asset.venue_id),
                    "author_type": "venue",
                    "occurred_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()
        return await self._build_upload_status(asset, story, now=now)

    async def get_upload_status(
        self, *, user: User, upload_id: UUID, now: datetime
    ) -> StoryUploadResponse:
        require_stories_enabled(self._settings)
        asset = await self._load_owned_story_asset(user, upload_id, purpose=None)
        story = await self._load_story_for_asset(asset.id)
        return await self._build_upload_status(asset, story, now=now)

    async def publish_after_moderation_approval(
        self, media_asset_id: UUID, *, now: datetime
    ) -> bool:
        return await publish_content_for_media_asset(
            self._session, media_asset_id, now=now, settings=self._settings
        )

    # --------------------------------------------------------------- views

    async def record_view(
        self, *, viewer: User, story_id: UUID, now: datetime
    ) -> RecordStoryViewResponse:
        require_stories_enabled(self._settings)
        await self._limits.check_view_soft(user_id=viewer.id, now=now)

        story = await self._load_story(story_id)
        if not is_publicly_viewable(story, now=now):
            if story.publication_status == "expired" or (
                story.expires_at is not None and story.expires_at <= now
            ):
                raise AppError("STORY_EXPIRED", "This Story has expired.", status_code=410)
            raise AppError("STORY_NOT_PUBLISHED", "This Story is not available.", status_code=404)

        stmt = (
            pg_insert(StoryView)
            .values(
                id=uuid4(),
                story_id=story.id,
                viewer_user_id=viewer.id,
                viewed_at=now,
                created_at=now,
            )
            .on_conflict_do_nothing(index_elements=["story_id", "viewer_user_id"])
            .returning(StoryView.viewed_at)
        )
        result = await self._session.execute(stmt)
        viewed_at = result.scalar_one_or_none()
        if viewed_at is None:
            existing = await self._session.execute(
                select(StoryView.viewed_at).where(
                    StoryView.story_id == story.id,
                    StoryView.viewer_user_id == viewer.id,
                )
            )
            viewed_at = existing.scalar_one()
        await self._session.commit()
        return RecordStoryViewResponse(story_id=story.id, viewed=True, viewed_at=viewed_at)

    # ------------------------------------------------------------- reports

    async def report_story(
        self,
        *,
        reporter: User,
        story_id: UUID,
        request: CreateStoryReportRequest,
        now: datetime,
    ) -> CreateStoryReportResponse:
        require_stories_enabled(self._settings)
        max_length = self._settings.vibe_report_description_max_length
        if request.description is not None and len(request.description) > max_length:
            raise AppError(
                "REPORT_DESCRIPTION_TOO_LONG",
                f"Report description exceeds {max_length} characters.",
                status_code=400,
                details={"max_length": max_length},
            )

        story = await self._load_story(story_id, for_update=True)
        if not is_publicly_viewable(story, now=now):
            raise AppError("STORY_NOT_FOUND", "Story not found.", status_code=404)

        is_own = story.author_user_id == reporter.id or story.created_by_user_id == reporter.id
        if is_own and story.author_type == "user":
            raise AppError(
                "CANNOT_REPORT_OWN_CONTENT",
                "You cannot report your own Story.",
                status_code=400,
            )

        await self._limits.check_report(user_id=reporter.id, now=now)

        report = StoryReport(
            id=uuid4(),
            story_id=story.id,
            reporter_user_id=reporter.id,
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
                "STORY_REPORT_DUPLICATE",
                "You already reported this Story.",
                status_code=409,
            ) from exc

        self._session.add(
            OutboxEvent(
                aggregate_type="story",
                aggregate_id=story.id,
                event_type="story.reported",
                payload={
                    "story_id": str(story.id),
                    "media_asset_id": str(story.media_asset_id),
                    "venue_id": str(story.venue_id),
                    "reason": request.reason,
                    "reported_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()
        return CreateStoryReportResponse(
            report_id=report.id,
            story_id=story.id,
            reason=request.reason,
            status="open",
            created_at=now,
        )

    # ------------------------------------------------------------- deletion

    async def delete_story(
        self, *, user: User, story_id: UUID, now: datetime
    ) -> DeleteStoryResponse:
        require_stories_enabled(self._settings)
        story = await self._load_story(story_id, for_update=True)
        if story.deleted_at is not None or story.publication_status == "deleted":
            raise AppError(
                "STORY_ALREADY_DELETED",
                "This Story was already deleted.",
                status_code=409,
            )

        if story.author_type == "user":
            if story.author_user_id != user.id:
                raise AppError(
                    "STORY_FORBIDDEN",
                    "You cannot delete this Story.",
                    status_code=403,
                )
            mark_deleted(story, now=now)
            event_type = "story.deleted"
        else:
            await self._authz.require_venue_permission(
                user, story.venue_id, OrgPermission.VENUE_CONTENT_PUBLISH
            )
            mark_deleted(story, now=now)
            event_type = "official_story.deleted"
            if story.organization_id is not None:
                await append_audit_event(
                    self._session,
                    event_type=OFFICIAL_STORY_DELETED,
                    actor_user_id=user.id,
                    organization_id=story.organization_id,
                    venue_id=story.venue_id,
                    target_type="story",
                    target_id=story.id,
                    metadata={"story_id": str(story.id)},
                )

        self._session.add(
            OutboxEvent(
                aggregate_type="story",
                aggregate_id=story.id,
                event_type=event_type,
                payload={
                    "story_id": str(story.id),
                    "venue_id": str(story.venue_id),
                    "media_asset_id": str(story.media_asset_id),
                    "deleted_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()
        return DeleteStoryResponse(story_id=story.id, publication_status="deleted")

    # ------------------------------------------------------------- grouping

    async def list_experience_story_groups(
        self, *, viewer: User, now: datetime
    ) -> StoryGroupListResponse:
        require_stories_enabled(self._settings)
        stories = await self._load_public_stories(now=now, limit=EXPERIENCE_STORY_LIMIT)
        if not stories:
            return StoryGroupListResponse(items=[])

        viewed_ids = await self._viewed_story_ids(
            viewer_id=viewer.id, story_ids=[s.id for s in stories]
        )
        venues = await self._venues_by_id({s.venue_id for s in stories})
        authors = await self._authors_by_id(
            {s.author_user_id for s in stories if s.author_user_id is not None}
        )
        assets = await self._assets_by_id({s.media_asset_id for s in stories})
        secret = self._settings.cursor_hmac_secret.get_secret_value()

        groups: dict[str, list[Story]] = {}
        for story in stories:
            lid = logical_group_id(
                author_type=story.author_type,
                attribution_mode=story.attribution_mode,
                venue_id=story.venue_id,
                author_user_id=story.author_user_id,
                story_id=story.id,
            )
            groups.setdefault(lid, []).append(story)

        summaries: list[tuple[bool, datetime, StoryGroupSummary]] = []
        for logical_id, members in groups.items():
            members_sorted = sorted(
                members,
                key=lambda s: (s.published_at or now, s.id),
                reverse=True,
            )
            latest = members_sorted[0]
            unviewed = sum(1 for s in members if s.id not in viewed_ids)
            active_count = len(members)
            earliest_expires = min(s.expires_at for s in members if s.expires_at is not None)
            latest_published = max(s.published_at for s in members if s.published_at is not None)
            is_official = latest.author_type == "venue" or latest.attribution_mode == "official"
            is_mine = self._is_mine(latest, viewer)
            author_label, author_proj = self._author_projection(latest, authors, venues, viewer)
            venue = venues.get(latest.venue_id)
            venue_proj = (
                VenueStoryProjection(id=venue.id, name=venue.name, slug=venue.slug)
                if venue is not None
                else None
            )
            preview: list[MediaVariant] = []
            asset = assets.get(latest.media_asset_id)
            if asset is not None and may_issue_content_signed_urls(
                asset, story=latest, post=None, now=now, settings=self._settings
            ):
                preview = await self._signed_variants(asset, now=now)

            if is_official:
                group_type = "venue"
            elif latest.attribution_mode == "anonymous":
                group_type = "anon"
            else:
                group_type = "user"
            summary = StoryGroupSummary(
                group_key=sign_group_key(logical_id=logical_id, secret=secret),
                group_type=group_type,  # type: ignore[arg-type]
                venue_id=latest.venue_id,
                author=author_proj,
                author_label=author_label,
                venue=venue_proj,
                is_official=is_official,
                is_mine=is_mine,
                preview_variants=preview,
                active_count=active_count,
                unviewed_count=unviewed,
                latest_published_at=latest_published,
                earliest_expires_at=earliest_expires,
            )
            summaries.append((unviewed > 0, latest_published, summary))

        summaries.sort(key=lambda row: (not row[0], -row[1].timestamp(), row[2].group_key))
        return StoryGroupListResponse(items=[row[2] for row in summaries])

    async def get_story_group(
        self, *, viewer: User, group_key: str, now: datetime
    ) -> StoryGroupDetail:
        require_stories_enabled(self._settings)
        secret = self._settings.cursor_hmac_secret.get_secret_value()
        verified = verify_group_key(group_key=group_key, secret=secret)
        logical_id = verified["logical_id"]
        stories = await self._stories_for_logical_group(logical_id, now=now)
        if not stories:
            raise AppError("STORY_NOT_FOUND", "Story group not found.", status_code=404)

        stories_asc = sorted(stories, key=lambda s: (s.published_at or now, s.id))
        viewed_ids = await self._viewed_story_ids(
            viewer_id=viewer.id, story_ids=[s.id for s in stories_asc]
        )
        venues = await self._venues_by_id({s.venue_id for s in stories_asc})
        authors = await self._authors_by_id(
            {s.author_user_id for s in stories_asc if s.author_user_id is not None}
        )
        assets = await self._assets_by_id({s.media_asset_id for s in stories_asc})

        head = stories_asc[0]
        is_official = head.author_type == "venue" or head.attribution_mode == "official"
        author_label, _ = self._author_projection(head, authors, venues, viewer)
        can_delete_official = False
        if is_official:
            can_delete_official = await self._can_publish(viewer, head.venue_id)
        slides: list[StorySlide] = []
        for story in stories_asc:
            label, author_proj = self._author_projection(story, authors, venues, viewer)
            venue = venues.get(story.venue_id)
            venue_proj = (
                VenueStoryProjection(id=venue.id, name=venue.name, slug=venue.slug)
                if venue is not None
                else None
            )
            is_mine = self._is_mine(story, viewer)
            asset = assets.get(story.media_asset_id)
            variants: list[MediaVariant] = []
            if asset is not None and may_issue_content_signed_urls(
                asset, story=story, post=None, now=now, settings=self._settings
            ):
                variants = await self._signed_variants(asset, now=now)
            slides.append(
                StorySlide(
                    story_id=story.id,
                    venue_id=story.venue_id,
                    media_type=asset.media_type if asset is not None else "image",  # type: ignore[arg-type]
                    attribution_mode=story.attribution_mode,  # type: ignore[arg-type]
                    author=author_proj,
                    author_label=label,
                    venue=venue_proj,
                    is_official=is_official,
                    caption=story.caption,
                    vibe_tags=list(story.vibe_tags or []),
                    reply_policy=story.reply_policy,  # type: ignore[arg-type]
                    published_at=story.published_at or now,
                    expires_at=story.expires_at or (now + STORY_PUBLIC_WINDOW),
                    viewed=story.id in viewed_ids,
                    is_mine=is_mine,
                    can_report=not is_mine,
                    can_delete=is_mine or can_delete_official,
                    variants=variants,
                )
            )

        return StoryGroupDetail(
            group_key=group_key,
            group_type=verified["group_type"],
            venue_id=head.venue_id,
            author_label=author_label,
            is_official=is_official,
            is_mine=any(s.is_mine for s in slides),
            slides=slides,
        )

    # --------------------------------------------------------------- helpers

    def _assert_user_eligible(self, user: User) -> None:
        if user.account_status != "active" or user.deleted_at is not None:
            raise AppError(
                "ACCOUNT_INACTIVE",
                "This account cannot post Stories.",
                status_code=403,
            )
        if user.onboarding_state == "age_ineligible":
            raise AppError(
                "AGE_INELIGIBLE",
                "This account does not meet the minimum age requirement.",
                status_code=403,
            )
        if user.onboarding_state != "completed":
            raise AppError(
                "ONBOARDING_INCOMPLETE",
                "Finish onboarding before posting Stories.",
                status_code=403,
            )

    async def _admit_uploaded_object(
        self,
        asset: MediaAsset,
        *,
        request: CompleteStoryUploadRequest,
        now: datetime,
    ) -> None:
        stat = await self._storage.stat_object(
            bucket=self._settings.media_quarantine_bucket,
            key=asset.quarantine_object_key,
        )
        if stat is None:
            raise AppError(
                "MEDIA_OBJECT_MISSING",
                "No uploaded object was found for this upload.",
                status_code=409,
            )
        if stat.byte_size != asset.declared_byte_size:
            raise AppError(
                "MEDIA_SIZE_MISMATCH",
                "Uploaded object size does not match the declared size.",
                status_code=409,
                details={
                    "declared_byte_size": asset.declared_byte_size,
                    "observed_byte_size": stat.byte_size,
                },
            )
        if request.checksum_sha256 is not None:
            summary = dict(asset.moderation_summary or {})
            summary["declared_checksum_sha256"] = request.checksum_sha256
            asset.moderation_summary = summary
        self._media_lifecycle.mark_uploaded(asset, now=now)

    async def _build_upload_status(
        self, asset: MediaAsset, story: Story, *, now: datetime
    ) -> StoryUploadResponse:
        variants: list[MediaVariant] = []
        if may_issue_content_signed_urls(
            asset, story=story, post=None, now=now, settings=self._settings
        ):
            variants = await self._signed_variants(asset, now=now)
        summary = asset.moderation_summary or {}
        failure_reason: str | None = None
        if asset.lifecycle_status in FAILURE_STATUSES:
            raw = summary.get("invalid_reason") or summary.get("error_category")
            failure_reason = str(raw) if raw is not None else asset.lifecycle_status
        return StoryUploadResponse(
            story_id=story.id,
            upload_id=asset.id,
            media_asset_id=asset.id,
            lifecycle_status=asset.lifecycle_status,  # type: ignore[arg-type]
            publication_status=story.publication_status,  # type: ignore[arg-type]
            moderation_status=asset.moderation_status,  # type: ignore[arg-type]
            attribution_mode=story.attribution_mode,  # type: ignore[arg-type]
            intent_expires_at=asset.intent_expires_at,
            max_byte_size=asset.declared_byte_size,
            variants=variants,
            failure_reason=failure_reason,
            expires_at=story.expires_at,
            published_at=story.published_at,
        )

    async def _signed_variants(self, asset: MediaAsset, *, now: datetime) -> list[MediaVariant]:
        result = await self._session.execute(
            select(MediaDerivative).where(
                MediaDerivative.media_asset_id == asset.id,
                MediaDerivative.generation == asset.generation,
                MediaDerivative.status == "ready",
            )
        )
        return await build_signed_variants(
            self._storage, self._settings, list(result.scalars().all()), now=now
        )

    async def _load_owned_story_asset(
        self,
        user: User,
        upload_id: UUID,
        *,
        purpose: str | None,
        for_update: bool = False,
    ) -> MediaAsset:
        stmt = select(MediaAsset).where(MediaAsset.id == upload_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        asset = result.scalar_one_or_none()
        if (
            asset is None
            or asset.owner_user_id != user.id
            or asset.lifecycle_status == "deleted"
            or asset.purpose not in {"user_story", "venue_owned"}
            or (purpose is not None and asset.purpose != purpose)
        ):
            raise AppError("STORY_NOT_FOUND", "Story upload not found.", status_code=404)
        return asset

    async def _load_story_for_asset(
        self, media_asset_id: UUID, *, for_update: bool = False
    ) -> Story:
        stmt = select(Story).where(Story.media_asset_id == media_asset_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        story = result.scalar_one_or_none()
        if story is None:
            raise AppError("STORY_NOT_FOUND", "Story upload not found.", status_code=404)
        return story

    async def _load_story(self, story_id: UUID, *, for_update: bool = False) -> Story:
        stmt = select(Story).where(Story.id == story_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        story = result.scalar_one_or_none()
        if story is None:
            raise AppError("STORY_NOT_FOUND", "Story not found.", status_code=404)
        return story

    async def _load_public_stories(self, *, now: datetime, limit: int) -> list[Story]:
        result = await self._session.execute(
            select(Story)
            .where(
                Story.publication_status == "published",
                Story.deleted_at.is_(None),
                Story.expires_at.is_not(None),
                Story.expires_at > now,
            )
            .order_by(Story.published_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _stories_for_logical_group(self, logical_id: str, *, now: datetime) -> list[Story]:
        base = and_(
            Story.publication_status == "published",
            Story.deleted_at.is_(None),
            Story.expires_at.is_not(None),
            Story.expires_at > now,
        )
        if logical_id.startswith("venue:"):
            venue_id = UUID(logical_id.split(":", 1)[1])
            clause = and_(
                base,
                Story.venue_id == venue_id,
                or_(Story.author_type == "venue", Story.attribution_mode == "official"),
            )
        elif logical_id.startswith("user:"):
            # user:{user_id}:venue:{venue_id}
            parts = logical_id.split(":")
            user_id = UUID(parts[1])
            venue_id = UUID(parts[3])
            clause = and_(
                base,
                Story.author_type == "user",
                Story.attribution_mode == "attributed",
                Story.author_user_id == user_id,
                Story.venue_id == venue_id,
            )
        elif logical_id.startswith("anon:"):
            # anon:{venue_id}:{story_id}
            parts = logical_id.split(":")
            story_id = UUID(parts[2])
            clause = and_(base, Story.id == story_id, Story.attribution_mode == "anonymous")
        else:
            raise AppError("STORY_GROUP_KEY_INVALID", "Unknown story group.", status_code=400)

        result = await self._session.execute(select(Story).where(clause))
        return list(result.scalars().all())

    async def _viewed_story_ids(self, *, viewer_id: UUID, story_ids: list[UUID]) -> set[UUID]:
        if not story_ids:
            return set()
        result = await self._session.execute(
            select(StoryView.story_id).where(
                StoryView.viewer_user_id == viewer_id,
                StoryView.story_id.in_(story_ids),
            )
        )
        return set(result.scalars().all())

    async def _venues_by_id(self, ids: set[UUID]) -> dict[UUID, Venue]:
        if not ids:
            return {}
        result = await self._session.execute(select(Venue).where(Venue.id.in_(ids)))
        return {v.id: v for v in result.scalars().all()}

    async def _authors_by_id(self, ids: set[UUID]) -> dict[UUID, User]:
        if not ids:
            return {}
        result = await self._session.execute(select(User).where(User.id.in_(ids)))
        return {u.id: u for u in result.scalars().all()}

    async def _assets_by_id(self, ids: set[UUID]) -> dict[UUID, MediaAsset]:
        if not ids:
            return {}
        result = await self._session.execute(select(MediaAsset).where(MediaAsset.id.in_(ids)))
        return {a.id: a for a in result.scalars().all()}

    @staticmethod
    def _is_mine(story: Story, viewer: User) -> bool:
        if story.author_type == "user":
            return story.author_user_id == viewer.id
        return story.created_by_user_id == viewer.id

    def _author_projection(
        self,
        story: Story,
        authors: dict[UUID, User],
        venues: dict[UUID, Venue],
        _viewer: User,
    ) -> tuple[str, StoryAuthorProjection | None]:
        if story.attribution_mode == "official" or story.author_type == "venue":
            venue = venues.get(story.venue_id)
            label = venue.name if venue is not None else "Venue"
            return label, None
        if story.attribution_mode == "anonymous":
            return "Anonymous", None
        author = authors.get(story.author_user_id) if story.author_user_id else None
        if author is None:
            return "Anonymous", None
        return author.display_name or author.handle, StoryAuthorProjection(
            id=author.id,
            handle=author.handle,
            display_name=author.display_name,
        )

    async def _can_publish(self, user: User, venue_id: UUID) -> bool:
        link = await self._session.execute(
            select(VenueOrganization)
            .where(
                VenueOrganization.venue_id == venue_id,
                VenueOrganization.status == ACTIVE_VENUE_LINK,
            )
            .limit(1)
        )
        if link.scalar_one_or_none() is None:
            return False
        try:
            await self._authz.require_venue_permission(
                user, venue_id, OrgPermission.VENUE_CONTENT_PUBLISH
            )
        except AppError:
            return False
        return True
