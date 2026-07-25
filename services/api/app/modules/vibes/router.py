from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import (
    CurrentUserContext,
    get_current_user,
    get_db,
    get_idempotency_service,
    optional_idempotency_key,
)
from app.core.config import Settings, get_settings
from app.db.session import get_redis
from app.modules.media.schemas import CreateReportRequest
from app.modules.vibes.service import VibeService
from app.shared.idempotency import IdempotencyContext, IdempotencyService
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["vibes"])


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


def _now(request: Request) -> datetime:
    return getattr(request.state, "server_time", datetime.now(UTC))


def _service(session: AsyncSession, settings: Settings) -> VibeService:
    return VibeService(session, get_redis(settings), settings)


@router.get("/venues/{venue_id}/vibes")
async def venue_vibes(
    request: Request,
    venue_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    cursor: str | None = Query(default=None),
    limit: int = Query(12, ge=1, le=30),
) -> dict[str, Any]:
    """Authenticated read. Presence is not required to browse a venue's feed."""
    service = _service(session, settings)
    data = await service.venue_feed(
        venue_id=venue_id,
        viewer=ctx.user,
        cursor=cursor,
        limit=min(limit, settings.vibe_feed_page_max),
        now=_now(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.get("/me/vibes")
async def my_vibes(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    cursor: str | None = Query(default=None),
    limit: int = Query(12, ge=1, le=30),
) -> dict[str, Any]:
    """Creator history: expired vibes stay as metadata; media URLs are retention-gated."""
    service = _service(session, settings)
    data = await service.creator_vibes(
        author=ctx.user,
        cursor=cursor,
        limit=min(limit, settings.vibe_feed_page_max),
        now=_now(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/vibes/{vibe_id}/reports")
async def report_vibe(
    request: Request,
    vibe_id: UUID,
    body: CreateReportRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str | None, Depends(optional_idempotency_key)],
) -> dict[str, Any]:
    service = _service(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.report(reporter=ctx.user, vibe_id=vibe_id, request=body, now=now)
        return 201, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    # The unique (reporter, vibe) constraint already makes a repeat report safe,
    # so the header is optional here rather than required.
    if idempotency_key is None:
        status, payload = await handler()
    else:
        status, payload = await idem.run(
            IdempotencyContext(
                user_id=str(ctx.user.id),
                method="POST",
                route=f"/v1/vibes/{vibe_id}/reports",
                body=body.model_dump(mode="json"),
                key=idempotency_key,
            ),
            handler,
            ttl_seconds=settings.idempotency_ttl_seconds,
        )
    response.status_code = status
    return payload


@router.delete("/vibes/{vibe_id}")
async def delete_vibe(
    request: Request,
    vibe_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = _service(session, settings)
    data = await service.delete(user=ctx.user, vibe_id=vibe_id, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )
