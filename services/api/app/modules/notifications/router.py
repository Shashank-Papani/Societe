"""HTTP + WebSocket routes for notifications and realtime tickets (Phase 9A)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import secrets
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import CurrentUserContext, get_current_user, get_db
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.models import User
from app.db.session import get_redis, get_session_factory
from app.modules.identity.service import IdentityService
from app.modules.notifications.schemas import (
    PreferencePatchRequest,
    PushTokenRegisterRequest,
    ReadAllNotificationsRequest,
    RealtimeTicketRequest,
    RealtimeTicketResponse,
)
from app.modules.notifications.service import NotificationService
from app.modules.notifications.tickets import (
    acquire_notification_connection_slot,
    authenticate_websocket_with_ticket,
    create_realtime_ticket,
    notifications_channel,
    release_notification_connection_slot,
    websocket_path_for_purpose,
)
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["notifications"])


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


def _now(request: Request) -> datetime:
    return getattr(request.state, "server_time", datetime.now(UTC))


def _service(session: AsyncSession, settings: Settings) -> NotificationService:
    return NotificationService(session, get_redis(settings), settings)


@router.get("/notifications")
async def list_notifications(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    unread_only: Annotated[bool, Query()] = False,
    category: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    data = await _service(session, settings).list_notifications(
        user=ctx.user,
        cursor=cursor,
        limit=limit,
        unread_only=unread_only,
        category=category,
        now=_now(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.get("/notifications/unread-count")
async def unread_count(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).unread_count(user=ctx.user, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).mark_read(
        user=ctx.user, notification_id=notification_id, now=_now(request)
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/notifications/read-all")
async def mark_all_read(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    body: ReadAllNotificationsRequest | None = None,
) -> dict[str, Any]:
    category = body.category if body is not None else None
    data = await _service(session, settings).mark_read_all(
        user=ctx.user, category=category, now=_now(request)
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.delete("/notifications/{notification_id}")
async def dismiss_notification(
    notification_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).dismiss(
        user=ctx.user, notification_id=notification_id, now=_now(request)
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.get("/me/notification-preferences")
async def get_notification_preferences(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).get_preferences(user=ctx.user)
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.patch("/me/notification-preferences")
async def patch_notification_preferences(
    body: PreferencePatchRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).patch_preferences(
        user=ctx.user, body=body, now=_now(request)
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.put("/me/devices/{device_id}/push-token")
async def register_push_token(
    device_id: UUID,
    body: PushTokenRegisterRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).register_push_token(
        user=ctx.user, device_id=device_id, body=body, now=_now(request)
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.delete("/me/devices/{device_id}/push-token")
async def delete_push_token(
    device_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).delete_push_token(
        user=ctx.user, device_id=device_id, now=_now(request)
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/realtime/tickets")
async def create_ticket(
    request: Request,
    body: RealtimeTicketRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    IdentityService(session).assert_active(ctx.user)
    redis = get_redis(settings)
    ticket, ttl = await create_realtime_ticket(
        redis,
        user_id=ctx.user.id,
        settings=settings,
        purpose=body.purpose,
    )
    data = RealtimeTicketResponse(
        ticket=ticket,
        expires_in_seconds=ttl,
        purpose=body.purpose,
        websocket_path=websocket_path_for_purpose(body.purpose),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.websocket("/realtime/notifications")
async def notifications_ws(websocket: WebSocket) -> None:
    settings = get_settings()
    redis = get_redis(settings)
    user_id: UUID | None = None
    connection_id: str | None = None
    pump: asyncio.Task[None] | None = None
    pubsub = None
    topic: str | None = None

    try:
        user_id = await authenticate_websocket_with_ticket(
            websocket, settings=settings, purpose="notifications"
        )
    except AppError:
        return
    except Exception:
        with contextlib.suppress(Exception):
            await websocket.close(code=4401)
        return

    connection_id = secrets.token_urlsafe(12)
    try:
        await acquire_notification_connection_slot(
            redis, user_id=user_id, connection_id=connection_id, settings=settings
        )
    except AppError:
        await websocket.close(code=4429)
        return

    factory = get_session_factory(settings)
    async with factory() as session:
        user = await session.get(User, user_id)
        if user is None or user.account_status != "active" or user.deleted_at is not None:
            await release_notification_connection_slot(
                redis, user_id=user_id, connection_id=connection_id
            )
            await websocket.close(code=4401)
            return
        notif_service = NotificationService(session, redis, settings)
        unread = await notif_service.unread_count(user=user, now=datetime.now(UTC))

    # Only after auth: initial unread snapshot (hints; REST remains authoritative).
    await websocket.send_json(
        {
            "type": "unread_count.changed",
            "payload": unread.model_dump(mode="json"),
        }
    )

    topic = notifications_channel(user_id)
    pubsub = redis.pubsub()
    await pubsub.subscribe(topic)

    async def _pump() -> None:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message is None:
                await asyncio.sleep(0.05)
                continue
            if message.get("type") != "message":
                continue
            raw = message.get("data")
            if not isinstance(raw, str):
                continue
            try:
                envelope = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await websocket.send_json(envelope)

    pump = asyncio.create_task(_pump())
    try:
        while True:
            raw = await websocket.receive_text()
            if raw.strip().lower() in {"ping", '{"type":"ping"}'}:
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        if pump is not None:
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump
        if pubsub is not None and topic is not None:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(topic)
                close = getattr(pubsub, "aclose", None) or pubsub.close
                result = close()
                if hasattr(result, "__await__"):
                    await result
        if user_id is not None and connection_id is not None:
            await release_notification_connection_slot(
                redis, user_id=user_id, connection_id=connection_id
            )
