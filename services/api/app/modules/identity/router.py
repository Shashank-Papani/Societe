from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import (
    CurrentUserContext,
    get_current_user,
    get_current_user_allow_inactive,
    get_db,
    get_idempotency_service,
    optional_idempotency_key,
    require_idempotency_key,
)
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import create_access_token
from app.modules.identity.service import IdentityService, serialize_device, serialize_user
from app.shared.idempotency import IdempotencyContext, IdempotencyService
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["identity"])


class LocalDevTokenRequest(BaseModel):
    note: str | None = None


class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    subject: str
    handle: str


class ProfilePatch(BaseModel):
    handle: str | None = Field(default=None, min_length=3, max_length=32)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    bio: str | None = Field(default=None, max_length=500)
    age_band: Literal["18-20", "21-24", "25-29", "30-34", "35+"] | None = None


class PrivacyPatch(BaseModel):
    ghost_mode: bool | None = None
    discoverable_in_venue: bool | None = None
    allow_calling_cards: bool | None = None
    show_social_links_after_accept: bool | None = None
    analytics_opt_out: bool | None = None


class DeviceCreate(BaseModel):
    platform: Literal["ios", "android"]
    installation_id: uuid.UUID
    app_version: str | None = None
    os_version: str | None = None


class AccountDeletionRequest(BaseModel):
    confirmation: Literal["DELETE"]


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


@router.post("/auth/local/token")
async def issue_local_dev_token(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    _body: LocalDevTokenRequest | None = None,
) -> dict[str, Any]:
    if settings.auth_provider != "local":
        raise AppError("NOT_FOUND", "Local auth is disabled.", status_code=404)
    if settings.app_env not in {"development", "test"}:
        raise AppError(
            "LOCAL_AUTH_FORBIDDEN",
            "Local auth is only available in development/test.",
            status_code=403,
        )
    service = IdentityService(session)
    user = await service.resolve_or_provision(settings.local_dev_subject)
    # Keep local handle aligned with configured local-dev handle for DX.
    if user.handle != settings.local_dev_handle:
        user.handle = settings.local_dev_handle
        await session.commit()
    token = create_access_token(
        subject=settings.local_dev_subject,
        handle=settings.local_dev_handle,
        settings=settings,
    )
    data = TokenData(
        access_token=token,
        expires_in_minutes=settings.jwt_access_token_minutes,
        subject=settings.local_dev_subject,
        handle=settings.local_dev_handle,
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.get("/me")
async def get_me(
    request: Request,
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    return success_response(serialize_user(ctx.user), meta=_meta(request)).model_dump(mode="json")


@router.patch("/me")
async def patch_me(
    request: Request,
    body: ProfilePatch,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str | None, Depends(optional_idempotency_key)],
) -> dict[str, Any]:
    service = IdentityService(session)
    payload = body.model_dump(exclude_unset=True)

    async def handler() -> tuple[int, dict[str, Any]]:
        user = await service.update_profile(ctx.user, payload)
        return 200, success_response(serialize_user(user), meta=_meta(request)).model_dump(
            mode="json"
        )

    if idempotency_key:
        status, body_out = await idem.run(
            IdempotencyContext(
                user_id=str(ctx.user.id),
                method="PATCH",
                route="/v1/me",
                body=payload,
                key=idempotency_key,
            ),
            handler,
        )
        response.status_code = status
        return body_out
    _, body_out = await handler()
    return body_out


@router.patch("/me/privacy")
async def patch_privacy(
    request: Request,
    body: PrivacyPatch,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str | None, Depends(optional_idempotency_key)],
) -> dict[str, Any]:
    service = IdentityService(session)
    payload = body.model_dump(exclude_unset=True)

    async def handler() -> tuple[int, dict[str, Any]]:
        user = await service.update_privacy(ctx.user, payload)
        return 200, success_response(serialize_user(user), meta=_meta(request)).model_dump(
            mode="json"
        )

    if idempotency_key:
        status, body_out = await idem.run(
            IdempotencyContext(
                user_id=str(ctx.user.id),
                method="PATCH",
                route="/v1/me/privacy",
                body=payload,
                key=idempotency_key,
            ),
            handler,
        )
        response.status_code = status
        return body_out
    _, body_out = await handler()
    return body_out


@router.post("/me/devices")
async def register_device(
    request: Request,
    body: DeviceCreate,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = IdentityService(session)
    payload = body.model_dump(mode="json")

    async def handler() -> tuple[int, dict[str, Any]]:
        device = await service.register_device(
            ctx.user,
            platform=body.platform,
            installation_id=body.installation_id,
            app_version=body.app_version,
            os_version=body.os_version,
        )
        return 200, success_response(serialize_device(device), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, body_out = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route="/v1/me/devices",
            body=payload,
            key=idempotency_key,
        ),
        handler,
    )
    response.status_code = status
    return body_out


@router.delete("/me/devices/{device_id}")
async def delete_device(
    request: Request,
    device_id: uuid.UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str | None, Depends(optional_idempotency_key)],
) -> dict[str, Any]:
    service = IdentityService(session)

    async def handler() -> tuple[int, dict[str, Any]]:
        await service.revoke_device(ctx.user, device_id)
        return 200, success_response({"revoked": True}, meta=_meta(request)).model_dump(mode="json")

    if idempotency_key:
        status, body_out = await idem.run(
            IdempotencyContext(
                user_id=str(ctx.user.id),
                method="DELETE",
                route=f"/v1/me/devices/{device_id}",
                body={},
                key=idempotency_key,
            ),
            handler,
        )
        response.status_code = status
        return body_out
    _, body_out = await handler()
    return body_out


@router.post("/me/account-deletion")
async def request_account_deletion(
    request: Request,
    body: AccountDeletionRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user_allow_inactive)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    """Soft-deletion request. Idempotency replay runs before account-status denial."""
    _ = body
    service = IdentityService(session)

    async def handler() -> tuple[int, dict[str, Any]]:
        result = await service.request_account_deletion(ctx.user)
        return 200, success_response(result, meta=_meta(request)).model_dump(mode="json")

    status, body_out = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route="/v1/me/account-deletion",
            body={"confirmation": "DELETE"},
            key=idempotency_key,
        ),
        handler,
    )
    response.status_code = status
    return body_out
