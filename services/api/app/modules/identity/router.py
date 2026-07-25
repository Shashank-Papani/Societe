from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import (
    CurrentUserContext,
    get_current_user,
    get_current_user_allow_inactive,
    get_current_user_for_reactivation,
    get_db,
    get_idempotency_service,
    optional_idempotency_key,
    require_idempotency_key,
)
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import create_access_token
from app.db.session import get_redis
from app.modules.identity.crypto_util import hash_optional
from app.modules.identity.dev_personas import resolve_dev_persona
from app.modules.identity.service import IdentityService, serialize_device, serialize_user
from app.modules.identity.session_service import SessionService
from app.shared.idempotency import IdempotencyContext, IdempotencyService
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["identity"])


class LocalDevTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    persona: str | None = None
    note: str | None = None


class TokenData(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    subject: str
    handle: str
    persona: str | None = None


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    bio: str | None = Field(default=None, max_length=500)
    interests: list[str] | None = None
    # Intentionally omitted: handle, age_verified, age_band, date_of_birth


class PrivacyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ghost_mode: bool | None = None
    discoverable_in_venue: bool | None = None
    allow_calling_cards: bool | None = None
    allow_messages_from_connections: bool | None = None
    show_social_links_after_accept: bool | None = None
    analytics_opt_out: bool | None = None
    notify_calling_cards: bool | None = None
    notify_messages: bool | None = None


class DeviceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["ios", "android"]
    installation_id: uuid.UUID
    app_version: str | None = None
    os_version: str | None = None


class AccountDeletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["DELETE"]


class AccountDeactivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["DEACTIVATE"]


class AccountReactivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["REACTIVATE"]
    platform: Literal["ios", "android"]
    installation_id: uuid.UUID
    app_version: str | None = None
    os_version: str | None = None


class OnboardingProfileBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str = Field(min_length=3, max_length=32)
    display_name: str = Field(min_length=1, max_length=80)


class OnboardingAgeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_of_birth: date


class OnboardingPoliciesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tos_version: str
    privacy_policy_version: str


class OnboardingPrivacyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    discoverable_in_venue: bool
    allow_calling_cards: bool
    allow_messages_from_connections: bool
    show_social_links_after_accept: bool
    ghost_mode: bool = False
    notify_calling_cards: bool = True
    notify_messages: bool = True


class ProfilePhotoUploadBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: uuid.UUID
    mime_type: str
    byte_size: int = Field(gt=0)


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


async def _serialize_me(session: AsyncSession, settings: Settings, user: Any) -> dict[str, Any]:
    service = IdentityService(session, settings)
    interests = await service.interests_for(user.id)
    photo = await service.approved_profile_photo_url(user)
    refreshed = await service._repo.get_by_id(user.id)
    assert refreshed is not None
    return serialize_user(
        refreshed,
        interests=interests,
        profile_photo_url=photo,
        settings=settings,
    )


@router.post("/auth/local/token")
async def issue_local_dev_token(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    body: LocalDevTokenRequest | None = None,
) -> dict[str, Any]:
    if settings.auth_provider != "local":
        raise AppError("NOT_FOUND", "Local auth is disabled.", status_code=404)
    if settings.app_env not in {"development", "test"}:
        raise AppError(
            "LOCAL_AUTH_FORBIDDEN",
            "Local auth is only available in development/test.",
            status_code=403,
        )

    service = IdentityService(session, settings)
    persona_key: str | None = body.persona if body is not None else None

    if persona_key is not None:
        persona = resolve_dev_persona(persona_key)
        subject = persona.subject
        handle = persona.handle
        display_name = persona.display_name
    else:
        subject = settings.local_dev_subject
        handle = settings.local_dev_handle
        display_name = "Local Dev"
        persona_key = None

    user = await service.resolve_or_provision(subject)
    if user.handle != handle:
        user.handle = handle
    user = await service.ensure_dev_persona_ready(user, display_name=display_name)

    token = create_access_token(subject=subject, handle=handle, settings=settings)
    data = TokenData(
        access_token=token,
        expires_in_minutes=settings.jwt_access_token_minutes,
        subject=subject,
        handle=handle,
        persona=persona_key,
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.get("/me")
async def get_me(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _serialize_me(session, settings, ctx.user)
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.patch("/me")
@router.patch("/me/profile")
async def patch_me(
    request: Request,
    body: ProfilePatch,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str | None, Depends(optional_idempotency_key)],
) -> dict[str, Any]:
    service = IdentityService(session, settings)
    payload = body.model_dump(exclude_unset=True)

    async def handler() -> tuple[int, dict[str, Any]]:
        user = await service.update_profile(ctx.user, payload)
        data = await _serialize_me(session, settings, user)
        return 200, success_response(data, meta=_meta(request)).model_dump(mode="json")

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


@router.get("/me/privacy")
async def get_privacy(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _serialize_me(session, settings, ctx.user)
    return success_response(data["privacy"], meta=_meta(request)).model_dump(mode="json")


@router.patch("/me/privacy")
async def patch_privacy(
    request: Request,
    body: PrivacyPatch,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str | None, Depends(optional_idempotency_key)],
) -> dict[str, Any]:
    service = IdentityService(session, settings)
    payload = body.model_dump(exclude_unset=True)

    async def handler() -> tuple[int, dict[str, Any]]:
        user = await service.update_privacy(ctx.user, payload)
        data = await _serialize_me(session, settings, user)
        return 200, success_response(data, meta=_meta(request)).model_dump(mode="json")

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


@router.get("/me/onboarding")
async def get_onboarding(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _serialize_me(session, settings, ctx.user)
    return success_response(
        {
            "onboarding_state": data["onboarding_state"],
            "onboarding_completed": data["onboarding_completed"],
            "required_policy_versions": data.get("required_policy_versions"),
            "minimum_age_years": data.get("minimum_age_years"),
        },
        meta=_meta(request),
    ).model_dump(mode="json")


@router.get("/me/username-availability")
async def username_availability(
    request: Request,
    handle: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = IdentityService(session, settings)
    available = await service.username_available(handle, excluding_user_id=ctx.user.id)
    return success_response({"available": available}, meta=_meta(request)).model_dump(mode="json")


@router.post("/me/onboarding/profile")
async def onboarding_profile(
    request: Request,
    body: OnboardingProfileBody,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = IdentityService(session, settings)
    user = await service.complete_onboarding_profile(
        ctx.user, handle=body.handle, display_name=body.display_name
    )
    data = await _serialize_me(session, settings, user)
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.post("/me/onboarding/age")
async def onboarding_age(
    request: Request,
    body: OnboardingAgeBody,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = IdentityService(session, settings)
    user = await service.complete_onboarding_age(ctx.user, date_of_birth=body.date_of_birth)
    data = await _serialize_me(session, settings, user)
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.post("/me/onboarding/policies")
async def onboarding_policies(
    request: Request,
    body: OnboardingPoliciesBody,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = IdentityService(session, settings)
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    user = await service.complete_onboarding_policies(
        ctx.user,
        tos_version=body.tos_version,
        privacy_policy_version=body.privacy_policy_version,
        ip_hash=hash_optional(ip, settings),
        user_agent_hash=hash_optional(ua, settings),
    )
    data = await _serialize_me(session, settings, user)
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.post("/me/onboarding/privacy")
async def onboarding_privacy(
    request: Request,
    body: OnboardingPrivacyBody,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = IdentityService(session, settings)
    user = await service.complete_onboarding_privacy(ctx.user, body.model_dump())
    data = await _serialize_me(session, settings, user)
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.post("/me/devices")
async def register_device(
    request: Request,
    body: DeviceCreate,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = IdentityService(session, settings)
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


@router.get("/me/devices")
async def list_devices(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = IdentityService(session, settings)
    devices = await service.list_devices(ctx.user)
    current_did = ctx.claims.get("did")
    data = [
        serialize_device(d, current=current_did is not None and str(d.id) == str(current_did))
        for d in devices
        if d.revoked_at is None
    ]
    return success_response({"devices": data}, meta=_meta(request)).model_dump(mode="json")


@router.delete("/me/devices/{device_id}")
async def delete_device(
    request: Request,
    device_id: uuid.UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str | None, Depends(optional_idempotency_key)],
) -> dict[str, Any]:
    service = IdentityService(session, settings)
    sessions = SessionService(session, get_redis(settings), settings)

    async def handler() -> tuple[int, dict[str, Any]]:
        await service.revoke_device(ctx.user, device_id, sessions=sessions)
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


@router.post("/me/profile-photo/uploads")
async def create_profile_photo_upload(
    request: Request,
    body: ProfilePhotoUploadBody,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    from app.modules.identity.profile_media import ProfileMediaService

    service = ProfileMediaService(session, settings)
    data = await service.create_upload(
        user=ctx.user,
        device_id=body.device_id,
        mime_type=body.mime_type,
        byte_size=body.byte_size,
    )
    await session.commit()
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.post("/me/profile-photo/uploads/{upload_id}/complete")
async def complete_profile_photo_upload(
    request: Request,
    upload_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    from app.modules.identity.profile_media import ProfileMediaService

    service = ProfileMediaService(session, settings)
    data = await service.complete_upload(user=ctx.user, upload_id=upload_id)
    await session.commit()
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.post("/me/account-deactivation")
async def deactivate_account(
    request: Request,
    body: AccountDeactivationRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    _ = body
    service = IdentityService(session, settings)
    sessions = SessionService(session, get_redis(settings), settings)
    result = await service.deactivate_account(ctx.user, sessions=sessions)
    return success_response(result, meta=_meta(request)).model_dump(mode="json")


@router.post("/me/account-reactivation")
async def reactivate_account(
    request: Request,
    body: AccountReactivationRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user_for_reactivation)],
) -> dict[str, Any]:
    service = IdentityService(session, settings)
    sessions = SessionService(session, get_redis(settings), settings)
    user, tokens = await service.reactivate_account(
        ctx.user,
        platform=body.platform,
        installation_id=body.installation_id,
        app_version=body.app_version,
        os_version=body.os_version,
        sessions=sessions,
    )
    data = await _serialize_me(session, settings, user)
    return success_response(
        {
            "status": "active",
            "user": data,
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": "bearer",
            "expires_in_minutes": tokens.expires_in_minutes,
            "device_id": str(tokens.device_id),
            "session_id": str(tokens.session_id),
        },
        meta=_meta(request),
    ).model_dump(mode="json")


@router.post("/me/account-deletion")
async def request_account_deletion(
    request: Request,
    body: AccountDeletionRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user_allow_inactive)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    _ = body
    service = IdentityService(session, settings)
    sessions = SessionService(session, get_redis(settings), settings)

    async def handler() -> tuple[int, dict[str, Any]]:
        result = await service.request_account_deletion(ctx.user, sessions=sessions)
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
