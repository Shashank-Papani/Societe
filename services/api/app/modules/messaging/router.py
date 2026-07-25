from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import (
    CurrentUserContext,
    get_current_user,
    get_db,
    get_idempotency_service,
)
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_redis
from app.modules.messaging.schemas import (
    CreateConversationRequest,
    MarkReadRequest,
    SendMessageRequest,
)
from app.modules.messaging.service import MessagingService
from app.shared.idempotency import IdempotencyContext, IdempotencyService
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["messaging"])


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


def _now(request: Request) -> datetime:
    return getattr(request.state, "server_time", datetime.now(UTC))


def _service(session: AsyncSession, settings: Settings) -> MessagingService:
    return MessagingService(session, get_redis(settings), settings)


def _resolve_message_idempotency_key(
    *,
    client_message_id: str,
    idempotency_key: str | None,
) -> str:
    """ADR 0016: Idempotency-Key must equal client_message_id when provided."""
    if idempotency_key is None or idempotency_key == "":
        return client_message_id
    if idempotency_key != client_message_id:
        raise AppError(
            "IDEMPOTENCY_KEY_MISMATCH",
            "Idempotency-Key must equal client_message_id.",
            status_code=400,
        )
    return client_message_id


@router.post("/conversations")
async def create_conversation(
    request: Request,
    body: CreateConversationRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).create_conversation(
        user=ctx.user,
        request=body,
        now=_now(request),
    )
    response.status_code = 201
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.get("/conversations")
async def list_conversations(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    include_archived: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    data = await _service(session, settings).list_conversations(
        user=ctx.user,
        cursor=cursor,
        limit=limit,
        include_archived=include_archived,
        now=_now(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    request: Request,
    conversation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).get_conversation(
        user=ctx.user,
        conversation_id=conversation_id,
        now=_now(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    request: Request,
    conversation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    data = await _service(session, settings).list_messages(
        user=ctx.user,
        conversation_id=conversation_id,
        cursor=cursor,
        limit=limit,
        now=_now(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    request: Request,
    conversation_id: UUID,
    body: SendMessageRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    key = _resolve_message_idempotency_key(
        client_message_id=body.client_message_id,
        idempotency_key=idempotency_key,
    )
    service = _service(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.send_message(
            user=ctx.user,
            conversation_id=conversation_id,
            request=body,
            now=now,
        )
        return 201, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, payload = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route=f"/v1/conversations/{conversation_id}/messages",
            body=body.model_dump(mode="json"),
            key=key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return payload


@router.post("/conversations/{conversation_id}/read")
async def mark_read(
    request: Request,
    conversation_id: UUID,
    body: MarkReadRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).mark_read(
        user=ctx.user,
        conversation_id=conversation_id,
        request=body,
        now=_now(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/conversations/{conversation_id}/archive")
async def archive_conversation(
    request: Request,
    conversation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).archive(
        user=ctx.user,
        conversation_id=conversation_id,
        now=_now(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/conversations/{conversation_id}/unarchive")
async def unarchive_conversation(
    request: Request,
    conversation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).unarchive(
        user=ctx.user,
        conversation_id=conversation_id,
        now=_now(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )
