"""Local realtime WebSocket hub and event acknowledgement (Phase 4).

The API process hosts ``WS /v1/realtime/ws`` (no separate realtime_hub worker).
Compose ``event-dispatcher`` publishes via ``LocalRealtimeHub`` into Valkey;
this endpoint subscribes to ``realtime:user:{id}`` and forwards envelopes.

Clients must deduplicate by ``event_id`` on reconnect / at-least-once delivery.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from redis.asyncio import Redis

from app.core.auth import get_identity_provider
from app.core.auth.deps import CurrentUserContext, get_current_user
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_redis, get_session_factory
from app.modules.identity.service import IdentityService
from app.modules.realtime.ack import record_event_ack
from app.modules.realtime.local import valkey_channel
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["realtime"])


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


def _extract_ws_token(websocket: WebSocket) -> str | None:
    auth = websocket.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip() or None
    query_token = websocket.query_params.get("access_token")
    if query_token:
        return query_token
    return None


async def _authenticate_ws(websocket: WebSocket, settings: Settings) -> UUID:
    token = _extract_ws_token(websocket)
    if not token:
        raise AppError("UNAUTHORIZED", "Bearer token required.", status_code=401)
    provider = get_identity_provider(settings)
    claims = await provider.verify_token(token)
    factory = get_session_factory(settings)
    async with factory() as session:
        service = IdentityService(session)
        user = await service.resolve_or_provision(claims.subject)
        service.assert_active(user)
        return user.id


@router.websocket("/realtime/ws")
async def realtime_ws(websocket: WebSocket) -> None:
    settings = get_settings()
    try:
        user_id = await _authenticate_ws(websocket, settings)
    except AppError:
        await websocket.close(code=4401)
        return
    except Exception:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    channel = f"user:{user_id}"
    topic = valkey_channel(channel)
    redis = get_redis(settings)
    pubsub = redis.pubsub()
    await pubsub.subscribe(topic)

    # Hint for clients: envelopes are at-least-once; dedupe by event_id.
    await websocket.send_json(
        {
            "type": "subscribed",
            "channel": channel,
            "note": "Clients must deduplicate by event_id.",
        }
    )

    async def _pump_pubsub() -> None:
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

    pump = asyncio.create_task(_pump_pubsub())
    try:
        while True:
            # Keep the socket open; clients may send pings or acks out-of-band via REST.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(topic)
            close = getattr(pubsub, "aclose", None) or pubsub.close
            result = close()
            if hasattr(result, "__await__"):
                await result


@router.post("/events/{event_id}/ack")
async def ack_event(
    request: Request,
    event_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    _ = ctx  # Authenticated caller only; ack is keyed by event_id for the dispatcher.
    redis: Redis[str] = get_redis(settings)
    await record_event_ack(
        redis,
        event_id=str(event_id),
        ttl_seconds=settings.realtime_ack_ttl_seconds,
    )
    return success_response(
        {"event_id": str(event_id), "acked": True},
        meta=_meta(request),
    ).model_dump(mode="json")
