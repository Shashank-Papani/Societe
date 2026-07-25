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
from app.modules.media.schemas import (
    CompleteUploadRequest,
    CreateUploadRequest,
)
from app.modules.media.service import MediaService
from app.shared.idempotency import IdempotencyContext, IdempotencyService
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["media"])


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


def _now(request: Request) -> datetime:
    """Server clock only. Intent windows must not be client-extendable."""
    return getattr(request.state, "server_time", datetime.now(UTC))


def _service(session: AsyncSession, settings: Settings) -> MediaService:
    return MediaService(session, get_redis(settings), settings)


@router.post("/media/uploads")
async def create_upload(
    request: Request,
    body: CreateUploadRequest,
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
        data = await service.create_upload(user=ctx.user, request=body, now=now)
        return 201, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, payload = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route="/v1/media/uploads",
            body=body.model_dump(mode="json"),
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return payload


@router.post("/media/uploads/{upload_id}/complete")
async def complete_upload(
    request: Request,
    upload_id: UUID,
    body: CompleteUploadRequest,
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
        data = await service.complete_upload(
            user=ctx.user, upload_id=upload_id, request=body, now=now
        )
        return 200, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, payload = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route=f"/v1/media/uploads/{upload_id}/complete",
            body=body.model_dump(mode="json"),
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return payload


@router.get("/media/uploads/{upload_id}")
async def get_upload(
    request: Request,
    upload_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = _service(session, settings)
    data = await service.get_upload(user=ctx.user, upload_id=upload_id, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )
