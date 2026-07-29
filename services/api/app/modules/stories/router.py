"""Stories and official venue content HTTP routes."""

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
from app.modules.stories.official_posts import OfficialPostService
from app.modules.stories.schemas import (
    CompleteStoryUploadRequest,
    CreateOfficialPostRequest,
    CreateOfficialStoryUploadRequest,
    CreateStoryReportRequest,
    CreateUserStoryUploadRequest,
)
from app.modules.stories.service import StoryService
from app.shared.idempotency import IdempotencyContext, IdempotencyService
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["stories"])


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


def _now(request: Request) -> datetime:
    return getattr(request.state, "server_time", datetime.now(UTC))


def _stories(session: AsyncSession, settings: Settings) -> StoryService:
    return StoryService(session, get_redis(settings), settings)


def _posts(session: AsyncSession, settings: Settings) -> OfficialPostService:
    return OfficialPostService(session, get_redis(settings), settings)


@router.post("/stories/uploads")
async def create_user_story_upload(
    request: Request,
    body: CreateUserStoryUploadRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _stories(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.create_user_story_upload(user=ctx.user, request=body, now=now)
        return 201, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, payload = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route="/v1/stories/uploads",
            body=body.model_dump(mode="json"),
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return payload


@router.post("/story-uploads/{upload_id}/complete")
async def complete_user_story_upload(
    request: Request,
    upload_id: UUID,
    body: CompleteStoryUploadRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _stories(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.complete_user_story_upload(
            user=ctx.user, upload_id=upload_id, request=body, now=now
        )
        return 200, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, payload = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route=f"/v1/story-uploads/{upload_id}/complete",
            body=body.model_dump(mode="json"),
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return payload


@router.get("/story-uploads/{upload_id}")
async def get_story_upload(
    request: Request,
    upload_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = _stories(session, settings)
    data = await service.get_upload_status(user=ctx.user, upload_id=upload_id, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/venues/{venue_id}/official-stories/uploads")
async def create_official_story_upload(
    request: Request,
    venue_id: UUID,
    body: CreateOfficialStoryUploadRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _stories(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.create_official_story_upload(
            user=ctx.user, venue_id=venue_id, request=body, now=now
        )
        return 201, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, payload = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route=f"/v1/venues/{venue_id}/official-stories/uploads",
            body=body.model_dump(mode="json"),
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return payload


@router.post("/official-story-uploads/{upload_id}/complete")
async def complete_official_story_upload(
    request: Request,
    upload_id: UUID,
    body: CompleteStoryUploadRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _stories(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.complete_official_story_upload(
            user=ctx.user, upload_id=upload_id, request=body, now=now
        )
        return 200, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, payload = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route=f"/v1/official-story-uploads/{upload_id}/complete",
            body=body.model_dump(mode="json"),
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return payload


@router.get("/experience/stories")
async def list_experience_stories(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = _stories(session, settings)
    data = await service.list_experience_story_groups(viewer=ctx.user, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.get("/story-groups/{group_key}")
async def get_story_group(
    request: Request,
    group_key: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = _stories(session, settings)
    data = await service.get_story_group(viewer=ctx.user, group_key=group_key, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/stories/{story_id}/views")
async def record_story_view(
    request: Request,
    story_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = _stories(session, settings)
    data = await service.record_view(viewer=ctx.user, story_id=story_id, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/stories/{story_id}/reports")
async def report_story(
    request: Request,
    story_id: UUID,
    body: CreateStoryReportRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _stories(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.report_story(
            reporter=ctx.user, story_id=story_id, request=body, now=now
        )
        return 201, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, payload = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route=f"/v1/stories/{story_id}/reports",
            body=body.model_dump(mode="json"),
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return payload


@router.delete("/stories/{story_id}")
async def delete_story(
    request: Request,
    story_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = _stories(session, settings)
    data = await service.delete_story(user=ctx.user, story_id=story_id, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/venues/{venue_id}/official-posts")
async def create_official_post(
    request: Request,
    venue_id: UUID,
    body: CreateOfficialPostRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _posts(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.create_post(user=ctx.user, venue_id=venue_id, request=body, now=now)
        return 201, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, payload = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route=f"/v1/venues/{venue_id}/official-posts",
            body=body.model_dump(mode="json"),
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return payload


@router.get("/venues/{venue_id}/official-posts")
async def list_official_posts(
    request: Request,
    venue_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    cursor: str | None = None,
) -> dict[str, Any]:
    _ = ctx
    service = _posts(session, settings)
    data = await service.list_public_posts(venue_id=venue_id, now=_now(request), cursor=cursor)
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.get("/official-posts/{post_id}")
async def get_official_post(
    request: Request,
    post_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    _ = ctx
    service = _posts(session, settings)
    data = await service.get_public_post(post_id=post_id, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/official-posts/{post_id}/archive")
async def archive_official_post(
    request: Request,
    post_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _posts(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.archive_post(user=ctx.user, post_id=post_id, now=now)
        return 200, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, payload = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route=f"/v1/official-posts/{post_id}/archive",
            body={},
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return payload


@router.delete("/official-posts/{post_id}")
async def delete_official_post_route(
    request: Request,
    post_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = _posts(session, settings)
    data = await service.delete_post(user=ctx.user, post_id=post_id, now=_now(request))
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )
