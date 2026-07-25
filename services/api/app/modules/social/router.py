from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import (
    CurrentUserContext,
    get_current_user,
    get_db,
    get_idempotency_service,
    require_idempotency_key,
)
from app.core.config import Settings, get_settings
from app.db.session import get_redis
from app.modules.social.schemas import (
    BlockUserRequest,
    CreateCallingCardRequest,
    RespondCallingCardRequest,
    ShareCallingCardRequest,
)
from app.modules.social.service import SocialService
from app.shared.idempotency import IdempotencyContext, IdempotencyService
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["social"])


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


def _now(request: Request) -> datetime:
    return getattr(request.state, "server_time", datetime.now(UTC))


def _service(session: AsyncSession, settings: Settings) -> SocialService:
    return SocialService(session, get_redis(settings), settings)


@router.get("/venues/me/discoverable-users")
async def discoverable_users(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    from app.modules.identity.social_gate import assert_socially_eligible

    assert_socially_eligible(ctx.user, action="venue_discovery")
    data = await _service(session, settings).discoverable_users(user=ctx.user, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.get("/me/blocked-users")
async def list_blocked_users(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).list_blocked_users(user=ctx.user)
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.post("/calling-cards")
async def create_calling_card(
    request: Request,
    body: CreateCallingCardRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _service(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.create_calling_card(
            user=ctx.user,
            request=body,
            idempotency_key=idempotency_key,
            now=now,
        )
        return 201, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, payload = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route="/v1/calling-cards",
            body=body.model_dump(mode="json"),
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return payload


@router.get("/calling-cards/inbox")
async def calling_card_inbox(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).inbox(user=ctx.user, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.get("/calling-cards/sent")
async def calling_card_sent(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).sent(user=ctx.user, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.get("/calling-cards/{calling_card_id}")
async def calling_card_detail(
    request: Request,
    calling_card_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).detail(
        user=ctx.user, calling_card_id=calling_card_id, now=_now(request)
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.get("/calling-cards/{calling_card_id}/status")
async def calling_card_status(
    request: Request,
    calling_card_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).status(
        user=ctx.user, calling_card_id=calling_card_id, now=_now(request)
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/calling-cards/{calling_card_id}/respond")
async def respond_calling_card(
    request: Request,
    calling_card_id: UUID,
    body: RespondCallingCardRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _service(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.respond(
            user=ctx.user,
            calling_card_id=calling_card_id,
            request=body,
            now=now,
        )
        return 200, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, payload = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route=f"/v1/calling-cards/{calling_card_id}/respond",
            body=body.model_dump(mode="json"),
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return payload


@router.post("/calling-cards/{calling_card_id}/cancel")
async def cancel_calling_card(
    request: Request,
    calling_card_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).cancel(
        user=ctx.user, calling_card_id=calling_card_id, now=_now(request)
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/calling-cards/{calling_card_id}/share")
async def share_calling_card(
    request: Request,
    calling_card_id: UUID,
    body: ShareCallingCardRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).share(
        user=ctx.user,
        calling_card_id=calling_card_id,
        request=body,
        now=_now(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/users/{user_id}/block")
async def block_user(
    request: Request,
    user_id: UUID,
    body: BlockUserRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).block_user(
        user=ctx.user,
        blocked_user_id=user_id,
        request=body,
        now=_now(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.delete("/users/{user_id}/block")
async def unblock_user(
    request: Request,
    user_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _service(session, settings).unblock_user(
        user=ctx.user,
        blocked_user_id=user_id,
        now=_now(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )
