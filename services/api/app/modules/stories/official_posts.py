"""Persistent official venue posts (announcements, events, etc.)."""

from __future__ import annotations

from datetime import datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4

from redis.asyncio import Redis
from sqlalchemy import DateTime, literal, select, tuple_
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import (
    MediaAsset,
    MediaDerivative,
    MediaProcessingJob,
    OfficialVenuePost,
    OutboxEvent,
    User,
    Venue,
)
from app.modules.media.access import may_issue_content_signed_urls
from app.modules.media.authz import validate_declared_media
from app.modules.media.lifecycle import MediaLifecycleService
from app.modules.media.schemas import CreateUploadRequest, MediaVariant
from app.modules.media.storage import ObjectStorage, build_object_storage, quarantine_object_key
from app.modules.media.urls import build_signed_variants
from app.modules.organizations.audit import (
    OFFICIAL_POST_ARCHIVED,
    OFFICIAL_POST_CREATED,
    OFFICIAL_POST_DELETED,
    append_audit_event,
)
from app.modules.organizations.authz import OrganizationAuthorizer, OrgPermission
from app.modules.stories.lifecycle import (
    archive_official_post,
    delete_official_post,
    is_official_post_public,
    publish_official_post,
    start_official_post_processing,
)
from app.modules.stories.rates import StoryRateLimiter
from app.modules.stories.schemas import (
    CreateOfficialPostRequest,
    OfficialPostCreateResponse,
    OfficialPostDetail,
    OfficialPostListResponse,
    OfficialPostSummary,
    OfficialPostUpload,
    UploadInstruction,
    VenueStoryProjection,
)
from app.modules.stories.service import require_stories_enabled
from app.shared.cursors import keyset_fingerprint, sign_keyset_cursor, verify_keyset_cursor

logger = get_logger(__name__)

CTA_URL_MAX_LENGTH = 2048
OFFICIAL_POST_PAGE_MAX = 30


def validate_cta_url(url: str | None) -> str | None:
    if url is None:
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    if len(cleaned) > CTA_URL_MAX_LENGTH:
        raise AppError(
            "OFFICIAL_POST_CTA_INVALID",
            f"CTA URL exceeds {CTA_URL_MAX_LENGTH} characters.",
            status_code=400,
        )
    parsed = urlparse(cleaned)
    if parsed.scheme != "https" or not parsed.netloc:
        raise AppError(
            "OFFICIAL_POST_CTA_INVALID",
            "CTA URL must be an https URL.",
            status_code=400,
        )
    return cleaned


class OfficialPostService:
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
        self._authz = OrganizationAuthorizer(session)
        self._limits = StoryRateLimiter(redis, settings)
        self._media_lifecycle = MediaLifecycleService()

    async def create_post(
        self,
        *,
        user: User,
        venue_id: UUID,
        request: CreateOfficialPostRequest,
        now: datetime,
    ) -> OfficialPostCreateResponse:
        require_stories_enabled(self._settings)
        ctx = await self._authz.require_venue_permission(
            user, venue_id, OrgPermission.VENUE_CONTENT_PUBLISH
        )
        await self._limits.check_official_post(organization_id=ctx.organization.id, now=now)

        venue = await self._session.get(Venue, venue_id)
        if venue is None:
            raise AppError("VENUE_NOT_FOUND", "Venue not found.", status_code=404)

        cta_url = validate_cta_url(request.call_to_action_url)
        has_media = request.media_type is not None
        post_id = uuid4()
        media_asset_id: UUID | None = None
        upload_payload: OfficialPostUpload | None = None

        if has_media:
            assert request.media_type is not None
            assert request.mime_type is not None
            assert request.byte_size is not None
            validate_declared_media(
                CreateUploadRequest(
                    venue_id=venue_id,
                    device_id=uuid4(),
                    media_type=request.media_type,
                    mime_type=request.mime_type,
                    byte_size=request.byte_size,
                    caption=None,
                    vibe_tags=[],
                    checksum_sha256=request.checksum_sha256,
                ),
                self._settings,
            )
            media_asset_id = uuid4()
            object_key = quarantine_object_key(
                owner_user_id=user.id,
                asset_id=media_asset_id,
                mime_type=request.mime_type,
            )
            intent_expires_at = now + timedelta(
                seconds=self._settings.media_upload_intent_ttl_seconds
            )
            asset = MediaAsset(
                id=media_asset_id,
                owner_user_id=user.id,
                venue_id=venue_id,
                purpose="venue_owned",
                organization_id=ctx.organization.id,
                author_check_in_id=None,
                device_id=None,
                media_type=request.media_type,
                lifecycle_status="intent_pending",
                moderation_status="pending",
                attribution_mode="attributed",
                quarantine_object_key=object_key,
                declared_mime_type=request.mime_type,
                declared_byte_size=request.byte_size,
                intent_expires_at=intent_expires_at,
                generation=1,
                moderation_summary=(
                    {"declared_checksum_sha256": request.checksum_sha256}
                    if request.checksum_sha256
                    else {}
                ),
                created_at=now,
            )
            self._session.add(asset)
            await self._session.flush()
            upload = await self._storage.presign_put(
                bucket=self._settings.media_quarantine_bucket,
                key=object_key,
                content_type=request.mime_type,
                expires_in=self._settings.media_presigned_put_ttl_seconds,
            )
            upload_payload = OfficialPostUpload(
                upload_id=media_asset_id,
                media_asset_id=media_asset_id,
                intent_expires_at=intent_expires_at,
                max_byte_size=request.byte_size,
                upload=UploadInstruction(
                    method="PUT",
                    url=upload.url,
                    headers=upload.headers,
                    expires_at=min(upload.expires_at, intent_expires_at),
                ),
            )

        post = OfficialVenuePost(
            id=post_id,
            venue_id=venue_id,
            organization_id=ctx.organization.id,
            created_by_user_id=user.id,
            media_asset_id=media_asset_id,
            post_type=request.post_type,
            title=request.title,
            body=request.body,
            call_to_action_type=request.call_to_action_type,
            call_to_action_url=cta_url,
            publication_status="draft",
            moderation_status="pending" if has_media else "approved",
            created_at=now,
            updated_at=now,
        )
        self._session.add(post)
        await self._session.flush()

        if not has_media:
            # Text-only announcements publish immediately (media is moderated).
            publish_official_post(post, now=now)
            event_type = "official_post.published"
        else:
            # Stay draft until upload completion + moderation approval.
            event_type = "official_post.created"

        await append_audit_event(
            self._session,
            event_type=OFFICIAL_POST_CREATED,
            actor_user_id=user.id,
            organization_id=ctx.organization.id,
            venue_id=venue_id,
            target_type="official_venue_post",
            target_id=post_id,
            metadata={
                "post_id": str(post_id),
                "post_type": request.post_type,
                "has_media": has_media,
            },
        )
        self._session.add(
            OutboxEvent(
                aggregate_type="official_venue_post",
                aggregate_id=post_id,
                event_type=event_type,
                payload={
                    "post_id": str(post_id),
                    "venue_id": str(venue_id),
                    "organization_id": str(ctx.organization.id),
                    "has_media": has_media,
                    "occurred_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()

        detail = await self._project_detail(post, now=now, include_unpublished=True)
        return OfficialPostCreateResponse(post=detail, upload=upload_payload)

    async def complete_media_upload(
        self,
        *,
        user: User,
        upload_id: UUID,
        now: datetime,
        checksum_sha256: str | None = None,
    ) -> OfficialPostDetail:
        """Complete the optional media PUT for an official post."""
        require_stories_enabled(self._settings)
        asset = await self._session.execute(
            select(MediaAsset).where(MediaAsset.id == upload_id).with_for_update()
        )
        media = asset.scalar_one_or_none()
        if (
            media is None
            or media.owner_user_id != user.id
            or media.purpose != "venue_owned"
            or media.lifecycle_status == "deleted"
        ):
            raise AppError(
                "OFFICIAL_POST_NOT_FOUND",
                "Official post upload not found.",
                status_code=404,
            )

        post_result = await self._session.execute(
            select(OfficialVenuePost)
            .where(OfficialVenuePost.media_asset_id == media.id)
            .with_for_update()
        )
        post = post_result.scalar_one_or_none()
        if post is None:
            raise AppError("OFFICIAL_POST_NOT_FOUND", "Official post not found.", status_code=404)

        await self._authz.require_venue_permission(
            user, post.venue_id, OrgPermission.VENUE_CONTENT_PUBLISH
        )

        if media.intent_consumed_at is not None or media.lifecycle_status != "intent_pending":
            if media.lifecycle_status == "upload_expired":
                raise AppError(
                    "STORY_UPLOAD_EXPIRED",
                    "The upload window expired. Start a new upload.",
                    status_code=409,
                )
            return await self._project_detail(post, now=now, include_unpublished=True)

        if now >= media.intent_expires_at:
            self._media_lifecycle.mark_intent_expired(media, now=now)
            await self._session.commit()
            raise AppError(
                "STORY_UPLOAD_EXPIRED",
                "The upload window expired. Start a new upload.",
                status_code=409,
            )

        stat = await self._storage.stat_object(
            bucket=self._settings.media_quarantine_bucket,
            key=media.quarantine_object_key,
        )
        if stat is None:
            raise AppError(
                "MEDIA_OBJECT_MISSING",
                "No uploaded object was found for this upload.",
                status_code=409,
            )
        if stat.byte_size != media.declared_byte_size:
            raise AppError(
                "MEDIA_SIZE_MISMATCH",
                "Uploaded object size does not match the declared size.",
                status_code=409,
                details={
                    "declared_byte_size": media.declared_byte_size,
                    "observed_byte_size": stat.byte_size,
                },
            )
        if checksum_sha256 is not None:
            summary = dict(media.moderation_summary or {})
            summary["declared_checksum_sha256"] = checksum_sha256
            media.moderation_summary = summary

        self._media_lifecycle.mark_uploaded(media, now=now)
        start_official_post_processing(post, now=now)
        self._session.add(
            MediaProcessingJob(
                media_asset_id=media.id,
                job_type="validate_process",
                status="pending",
                next_attempt_at=now,
                created_at=now,
            )
        )
        await self._session.commit()
        return await self._project_detail(post, now=now, include_unpublished=True)

    async def list_public_posts(
        self,
        *,
        venue_id: UUID,
        now: datetime,
        cursor: str | None = None,
        limit: int = OFFICIAL_POST_PAGE_MAX,
    ) -> OfficialPostListResponse:
        page = min(max(limit, 1), OFFICIAL_POST_PAGE_MAX)
        qfp = keyset_fingerprint(venue_id=str(venue_id), kind="official_posts")
        secret = self._settings.cursor_hmac_secret.get_secret_value()

        stmt = (
            select(OfficialVenuePost)
            .where(
                OfficialVenuePost.venue_id == venue_id,
                OfficialVenuePost.publication_status == "published",
                OfficialVenuePost.deleted_at.is_(None),
                OfficialVenuePost.archived_at.is_(None),
            )
            .order_by(OfficialVenuePost.published_at.desc(), OfficialVenuePost.id.desc())
            .limit(page + 1)
        )
        if cursor:
            payload = verify_keyset_cursor(cursor=cursor, expected_qfp=qfp, secret=secret)
            stmt = stmt.where(
                tuple_(OfficialVenuePost.published_at, OfficialVenuePost.id)
                < tuple_(
                    literal(
                        datetime.fromisoformat(str(payload["sk"])),
                        DateTime(timezone=True),
                    ),
                    literal(UUID(str(payload["id"])), PostgresUUID(as_uuid=True)),
                )
            )

        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        next_cursor = None
        if len(rows) > page:
            last = rows[page - 1]
            rows = rows[:page]
            assert last.published_at is not None
            next_cursor = sign_keyset_cursor(
                sort_key=last.published_at.isoformat(),
                item_id=str(last.id),
                qfp=qfp,
                secret=secret,
            )

        items = [await self._project_summary(p, now=now) for p in rows]
        return OfficialPostListResponse(items=items, next_cursor=next_cursor)

    async def get_public_post(self, *, post_id: UUID, now: datetime) -> OfficialPostDetail:
        post = await self._session.get(OfficialVenuePost, post_id)
        if post is None or not is_official_post_public(post):
            raise AppError("OFFICIAL_POST_NOT_FOUND", "Official post not found.", status_code=404)
        return await self._project_detail(post, now=now, include_unpublished=False)

    async def archive_post(self, *, user: User, post_id: UUID, now: datetime) -> OfficialPostDetail:
        post = await self._load_managed_post(user, post_id, for_update=True)
        archive_official_post(post, now=now)
        await append_audit_event(
            self._session,
            event_type=OFFICIAL_POST_ARCHIVED,
            actor_user_id=user.id,
            organization_id=post.organization_id,
            venue_id=post.venue_id,
            target_type="official_venue_post",
            target_id=post.id,
            metadata={"post_id": str(post.id)},
        )
        self._session.add(
            OutboxEvent(
                aggregate_type="official_venue_post",
                aggregate_id=post.id,
                event_type="official_post.archived",
                payload={
                    "post_id": str(post.id),
                    "venue_id": str(post.venue_id),
                    "archived_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()
        return await self._project_detail(post, now=now, include_unpublished=True)

    async def delete_post(self, *, user: User, post_id: UUID, now: datetime) -> OfficialPostDetail:
        post = await self._load_managed_post(user, post_id, for_update=True)
        delete_official_post(post, now=now)
        await append_audit_event(
            self._session,
            event_type=OFFICIAL_POST_DELETED,
            actor_user_id=user.id,
            organization_id=post.organization_id,
            venue_id=post.venue_id,
            target_type="official_venue_post",
            target_id=post.id,
            metadata={"post_id": str(post.id)},
        )
        self._session.add(
            OutboxEvent(
                aggregate_type="official_venue_post",
                aggregate_id=post.id,
                event_type="official_post.deleted",
                payload={
                    "post_id": str(post.id),
                    "venue_id": str(post.venue_id),
                    "deleted_at": now.isoformat(),
                },
                occurred_at=now,
                available_at=now,
            )
        )
        await self._session.commit()
        return await self._project_detail(post, now=now, include_unpublished=True)

    async def _load_managed_post(
        self, user: User, post_id: UUID, *, for_update: bool = False
    ) -> OfficialVenuePost:
        stmt = select(OfficialVenuePost).where(OfficialVenuePost.id == post_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        post = result.scalar_one_or_none()
        if post is None or post.deleted_at is not None:
            raise AppError("OFFICIAL_POST_NOT_FOUND", "Official post not found.", status_code=404)
        await self._authz.require_venue_permission(
            user, post.venue_id, OrgPermission.VENUE_CONTENT_PUBLISH
        )
        return post

    async def _project_summary(
        self, post: OfficialVenuePost, *, now: datetime
    ) -> OfficialPostSummary:
        variants = await self._variants_for_post(post, now=now)
        venue = await self._session.get(Venue, post.venue_id)
        venue_proj = (
            VenueStoryProjection(id=venue.id, name=venue.name, slug=venue.slug)
            if venue is not None
            else None
        )
        author_label = venue.name if venue is not None else "Venue"
        return OfficialPostSummary(
            post_id=post.id,
            venue_id=post.venue_id,
            post_type=post.post_type,  # type: ignore[arg-type]
            title=post.title,
            body=post.body,
            call_to_action_type=post.call_to_action_type,
            call_to_action_url=post.call_to_action_url,
            publication_status=post.publication_status,  # type: ignore[arg-type]
            published_at=post.published_at,
            is_official=True,
            author_label=author_label,
            venue=venue_proj,
            variants=variants,
        )

    async def _project_detail(
        self,
        post: OfficialVenuePost,
        *,
        now: datetime,
        include_unpublished: bool,
    ) -> OfficialPostDetail:
        _ = include_unpublished
        summary = await self._project_summary(post, now=now)
        return OfficialPostDetail(
            **summary.model_dump(),
            created_at=post.created_at,
        )

    async def _variants_for_post(
        self, post: OfficialVenuePost, *, now: datetime
    ) -> list[MediaVariant]:
        if post.media_asset_id is None:
            return []
        asset = await self._session.get(MediaAsset, post.media_asset_id)
        if asset is None or not may_issue_content_signed_urls(
            asset, story=None, post=post, now=now, settings=self._settings
        ):
            return []
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
