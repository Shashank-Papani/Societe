"""Inbox, preferences, and push-token registration (Phase 9A)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import DateTime, and_, func, literal, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import Notification, NotificationPreference, User, UserDevice
from app.modules.notifications.constants import (
    CATEGORY_DEFAULTS,
    MANDATORY_IN_APP_CATEGORIES,
    NOTIFICATION_CATEGORIES,
    TYPE_TO_CATEGORY,
    category_for_type,
)
from app.modules.notifications.push import (
    disable_device_push,
    hash_push_token,
    rate_limit_push_registration,
    token_suffix,
    validate_expo_token,
)
from app.modules.notifications.realtime_publish import publish_notification_hint
from app.modules.notifications.schemas import (
    DismissNotificationResponse,
    NotificationActorProjection,
    NotificationItem,
    NotificationListResponse,
    PreferenceItem,
    PreferenceListResponse,
    PreferencePatchRequest,
    PushTokenDeleteResponse,
    PushTokenRegisterRequest,
    PushTokenRegisterResponse,
    ReadAllNotificationsResponse,
    ReadNotificationResponse,
    UnreadCountResponse,
)
from app.shared.cursors import keyset_fingerprint, sign_keyset_cursor, verify_keyset_cursor

LIST_NAME = "notifications_inbox"


class NotificationService:
    def __init__(
        self,
        session: AsyncSession,
        redis: Redis[str],
        settings: Settings,
    ) -> None:
        self._session = session
        self._redis = redis
        self._settings = settings

    def _assert_active(self, user: User) -> None:
        if user.account_status != "active" or user.deleted_at is not None:
            raise AppError("UNAUTHORIZED", "Account is not active.", status_code=401)

    async def list_notifications(
        self,
        *,
        user: User,
        cursor: str | None,
        limit: int,
        unread_only: bool,
        category: str | None,
        now: datetime,
    ) -> NotificationListResponse:
        self._assert_active(user)
        if category is not None and category not in NOTIFICATION_CATEGORIES:
            raise AppError(
                "NOTIFICATION_CATEGORY_INVALID",
                "Unknown notification category.",
                status_code=400,
            )
        page_size = min(max(limit, 1), 50)
        qfp = keyset_fingerprint(
            list=LIST_NAME,
            user_id=str(user.id),
            unread_only=unread_only,
            category=category or "",
        )

        types_for_category = (
            [t for t, c in TYPE_TO_CATEGORY.items() if c == category] if category else None
        )

        stmt = (
            select(Notification)
            .where(
                Notification.recipient_user_id == user.id,
                Notification.dismissed_at.is_(None),
                or_(Notification.expires_at.is_(None), Notification.expires_at > now),
            )
            .order_by(Notification.latest_event_at.desc(), Notification.id.desc())
            .limit(page_size + 1)
        )
        if unread_only:
            stmt = stmt.where(Notification.read_at.is_(None))
        if types_for_category is not None:
            stmt = stmt.where(Notification.notification_type.in_(types_for_category))

        if cursor:
            payload = verify_keyset_cursor(
                cursor=cursor,
                expected_qfp=qfp,
                secret=self._settings.cursor_hmac_secret.get_secret_value(),
            )
            sort_raw = payload["sk"]
            stmt = stmt.where(
                tuple_(Notification.latest_event_at, Notification.id)
                < tuple_(
                    literal(datetime.fromisoformat(str(sort_raw)), DateTime(timezone=True)),
                    literal(UUID(str(payload["id"])), PostgresUUID(as_uuid=True)),
                )
            )

        rows = list((await self._session.execute(stmt)).scalars().all())
        page = rows[:page_size]
        items = [await self._to_item(row) for row in page]
        next_cursor: str | None = None
        if len(rows) > page_size and page:
            last = page[-1]
            next_cursor = sign_keyset_cursor(
                sort_key=last.latest_event_at.isoformat(),
                item_id=str(last.id),
                qfp=qfp,
                secret=self._settings.cursor_hmac_secret.get_secret_value(),
            )
        return NotificationListResponse(items=items, next_cursor=next_cursor)

    async def unread_count(self, *, user: User, now: datetime) -> UnreadCountResponse:
        self._assert_active(user)
        base = and_(
            Notification.recipient_user_id == user.id,
            Notification.read_at.is_(None),
            Notification.dismissed_at.is_(None),
            or_(Notification.expires_at.is_(None), Notification.expires_at > now),
        )
        total = int(
            await self._session.scalar(select(func.count()).select_from(Notification).where(base))
            or 0
        )
        by_category = {cat: 0 for cat in NOTIFICATION_CATEGORIES}
        rows = (
            await self._session.execute(
                select(Notification.notification_type, func.count())
                .where(base)
                .group_by(Notification.notification_type)
            )
        ).all()
        for ntype, count in rows:
            cat = TYPE_TO_CATEGORY.get(str(ntype))
            if cat is not None:
                by_category[cat] = by_category.get(cat, 0) + int(count)
        return UnreadCountResponse(total=total, by_category=by_category)

    async def mark_read(
        self, *, user: User, notification_id: UUID, now: datetime
    ) -> ReadNotificationResponse:
        self._assert_active(user)
        row = await self._load_owned(user.id, notification_id)
        if row.read_at is None:
            row.read_at = now
            row.updated_at = now
            await self._session.commit()
            await self._emit_unread(user.id, now)
            await publish_notification_hint(
                self._redis,
                user_id=user.id,
                event_type="notification.read",
                payload={"notification_id": str(row.id)},
            )
        else:
            await self._session.commit()
        return ReadNotificationResponse(
            notification_id=row.id, read=True, read_at=row.read_at or now
        )

    async def mark_read_all(
        self, *, user: User, category: str | None, now: datetime
    ) -> ReadAllNotificationsResponse:
        self._assert_active(user)
        if category is not None and category not in NOTIFICATION_CATEGORIES:
            raise AppError(
                "NOTIFICATION_CATEGORY_INVALID",
                "Unknown notification category.",
                status_code=400,
            )
        conditions = [
            Notification.recipient_user_id == user.id,
            Notification.read_at.is_(None),
            Notification.dismissed_at.is_(None),
            or_(Notification.expires_at.is_(None), Notification.expires_at > now),
        ]
        if category is not None:
            types = [t for t, c in TYPE_TO_CATEGORY.items() if c == category]
            conditions.append(Notification.notification_type.in_(types))
        result = await self._session.execute(
            update(Notification)
            .where(and_(*conditions))
            .values(read_at=now, updated_at=now)
            .returning(Notification.id)
        )
        changed = len(result.fetchall())
        await self._session.commit()
        if changed:
            await self._emit_unread(user.id, now)
        return ReadAllNotificationsResponse(changed_count=changed)

    async def dismiss(
        self, *, user: User, notification_id: UUID, now: datetime
    ) -> DismissNotificationResponse:
        self._assert_active(user)
        row = await self._load_owned(user.id, notification_id)
        if row.dismissed_at is None:
            row.dismissed_at = now
            row.updated_at = now
            # Free coalesce dedupe key for future messages.
            if row.notification_type == "message.received" and ":dismissed:" not in row.dedupe_key:
                row.dedupe_key = f"{row.dedupe_key}:dismissed:{row.id}"
            await self._session.commit()
            await self._emit_unread(user.id, now)
            await publish_notification_hint(
                self._redis,
                user_id=user.id,
                event_type="notification.dismissed",
                payload={"notification_id": str(row.id)},
            )
        else:
            await self._session.commit()
        return DismissNotificationResponse(
            notification_id=row.id,
            dismissed=True,
            dismissed_at=row.dismissed_at or now,
        )

    async def get_preferences(self, *, user: User) -> PreferenceListResponse:
        self._assert_active(user)
        await self._ensure_preferences(user.id)
        rows = list(
            (
                await self._session.execute(
                    select(NotificationPreference).where(NotificationPreference.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        by_cat = {r.category: r for r in rows}
        items: list[PreferenceItem] = []
        for cat in NOTIFICATION_CATEGORIES:
            row = by_cat.get(cat)
            defaults = CATEGORY_DEFAULTS[cat]
            items.append(
                PreferenceItem(
                    category=cat,
                    in_app_enabled=row.in_app_enabled if row else defaults["in_app_enabled"],
                    push_enabled=row.push_enabled if row else defaults["push_enabled"],
                )
            )
        return PreferenceListResponse(items=items)

    async def patch_preferences(
        self, *, user: User, body: PreferencePatchRequest, now: datetime
    ) -> PreferenceListResponse:
        self._assert_active(user)
        await self._ensure_preferences(user.id)
        for item in body.items:
            if item.category not in NOTIFICATION_CATEGORIES:
                raise AppError(
                    "NOTIFICATION_CATEGORY_INVALID",
                    "Unknown notification category.",
                    status_code=400,
                )
            row = await self._session.scalar(
                select(NotificationPreference).where(
                    NotificationPreference.user_id == user.id,
                    NotificationPreference.category == item.category,
                )
            )
            if row is None:
                defaults = CATEGORY_DEFAULTS[item.category]
                row = NotificationPreference(
                    user_id=user.id,
                    category=item.category,
                    in_app_enabled=defaults["in_app_enabled"],
                    push_enabled=defaults["push_enabled"],
                    created_at=now,
                    updated_at=now,
                )
                self._session.add(row)
            if item.in_app_enabled is not None:
                if item.category in MANDATORY_IN_APP_CATEGORIES and item.in_app_enabled is False:
                    raise AppError(
                        "NOTIFICATION_CATEGORY_INVALID",
                        "Account notifications cannot disable in-app delivery.",
                        status_code=400,
                    )
                row.in_app_enabled = item.in_app_enabled
            if item.push_enabled is not None:
                row.push_enabled = item.push_enabled
            row.updated_at = now
        await self._session.commit()
        return await self.get_preferences(user=user)

    async def register_push_token(
        self,
        *,
        user: User,
        device_id: UUID,
        body: PushTokenRegisterRequest,
        now: datetime,
    ) -> PushTokenRegisterResponse:
        self._assert_active(user)
        await rate_limit_push_registration(self._redis, user_id=user.id)
        validate_expo_token(body.token)
        device = await self._session.scalar(
            select(UserDevice).where(UserDevice.id == device_id).with_for_update()
        )
        if device is None or device.user_id != user.id:
            # Avoid enumeration: same shape as not found for foreign devices.
            raise AppError("DEVICE_NOT_FOUND", "Device not found.", status_code=404)
        if device.revoked_at is not None:
            raise AppError("DEVICE_REVOKED", "Device has been revoked.", status_code=403)

        token_hash = hash_push_token(body.token.strip())
        conflict = await self._session.scalar(
            select(UserDevice).where(
                UserDevice.push_token_hash == token_hash,
                UserDevice.push_enabled.is_(True),
                UserDevice.push_invalidated_at.is_(None),
                UserDevice.revoked_at.is_(None),
                UserDevice.user_id != user.id,
            )
        )
        if conflict is not None:
            raise AppError(
                "PUSH_TOKEN_CONFLICT",
                "Push token is already registered to another account.",
                status_code=409,
            )

        # Idempotent re-register on same or another owned device: clear other owned actives.
        others = list(
            (
                await self._session.execute(
                    select(UserDevice).where(
                        UserDevice.user_id == user.id,
                        UserDevice.id != device.id,
                        UserDevice.push_token_hash == token_hash,
                        UserDevice.push_enabled.is_(True),
                        UserDevice.push_invalidated_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for other in others:
            disable_device_push(other, now=now)

        device.push_provider = body.provider
        device.push_token_hash = token_hash
        device.push_token_suffix = token_suffix(body.token.strip())
        device.push_enabled = True
        device.push_last_registered_at = now
        device.push_invalidated_at = None
        device.push_failure_count = 0
        await self._session.commit()
        return PushTokenRegisterResponse(registered=True, provider="expo", device_id=device.id)

    async def delete_push_token(
        self, *, user: User, device_id: UUID, now: datetime
    ) -> PushTokenDeleteResponse:
        self._assert_active(user)
        device = await self._session.scalar(
            select(UserDevice).where(UserDevice.id == device_id).with_for_update()
        )
        if device is None or device.user_id != user.id:
            raise AppError("DEVICE_NOT_FOUND", "Device not found.", status_code=404)
        if device.revoked_at is not None:
            raise AppError("DEVICE_REVOKED", "Device has been revoked.", status_code=403)
        disable_device_push(device, now=now)
        await self._session.commit()
        return PushTokenDeleteResponse(disabled=True, device_id=device.id)

    async def _load_owned(self, user_id: UUID, notification_id: UUID) -> Notification:
        # Ownership is enforced in SQL so another user's row is never locked/loaded.
        row = await self._session.scalar(
            select(Notification)
            .where(
                Notification.id == notification_id,
                Notification.recipient_user_id == user_id,
            )
            .with_for_update()
        )
        if row is None:
            raise AppError(
                "NOTIFICATION_NOT_FOUND",
                "Notification was not found.",
                status_code=404,
            )
        return row

    async def _ensure_preferences(self, user_id: UUID) -> None:
        now = datetime.now(UTC)
        existing = {
            r.category
            for r in (
                await self._session.execute(
                    select(NotificationPreference).where(NotificationPreference.user_id == user_id)
                )
            )
            .scalars()
            .all()
        }
        for cat in NOTIFICATION_CATEGORIES:
            if cat in existing:
                continue
            defaults = CATEGORY_DEFAULTS[cat]
            self._session.add(
                NotificationPreference(
                    user_id=user_id,
                    category=cat,
                    in_app_enabled=defaults["in_app_enabled"],
                    push_enabled=defaults["push_enabled"],
                    created_at=now,
                    updated_at=now,
                )
            )
        await self._session.flush()

    async def _emit_unread(self, user_id: UUID, now: datetime) -> None:
        base = and_(
            Notification.recipient_user_id == user_id,
            Notification.read_at.is_(None),
            Notification.dismissed_at.is_(None),
            or_(Notification.expires_at.is_(None), Notification.expires_at > now),
        )
        total = int(
            await self._session.scalar(select(func.count()).select_from(Notification).where(base))
            or 0
        )
        await publish_notification_hint(
            self._redis,
            user_id=user_id,
            event_type="unread_count.changed",
            payload={"total": total},
        )

    async def _to_item(self, row: Notification) -> NotificationItem:
        actor: NotificationActorProjection | None = None
        if row.actor_user_id is not None:
            user = await self._session.get(User, row.actor_user_id)
            if user is None or user.deleted_at is not None or user.account_status == "deleted":
                actor = NotificationActorProjection(label="Someone")
            else:
                actor = NotificationActorProjection(
                    id=user.id,
                    handle=user.handle,
                    display_name=user.display_name,
                    label=user.display_name or user.handle or "Someone",
                )
        return NotificationItem(
            notification_id=row.id,
            notification_type=row.notification_type,
            category=category_for_type(row.notification_type),
            title=row.title,
            body=row.body,
            deep_link=row.deep_link,
            occurrence_count=row.occurrence_count,
            priority="high" if row.priority == "high" else "normal",
            read=row.read_at is not None,
            actor=actor,
            venue_id=row.venue_id,
            conversation_id=row.conversation_id,
            calling_card_id=row.calling_card_id,
            story_id=row.story_id,
            organization_id=row.organization_id,
            venue_claim_id=row.venue_claim_id,
            latest_event_at=row.latest_event_at,
            created_at=row.created_at,
        )
