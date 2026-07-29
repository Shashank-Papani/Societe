"""Organization and venue-management HTTP routes."""

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
from app.modules.organizations.claims import ClaimService
from app.modules.organizations.cover import CoverService
from app.modules.organizations.managed import ManagedVenueService
from app.modules.organizations.schemas import (
    CreateInvitationRequest,
    CreateOrganizationRequest,
    ManagedVenueProfileUpdate,
    SetVenueCoverRequest,
    SubmitVenueClaimRequest,
    UpdateMemberRoleRequest,
)
from app.modules.organizations.service import OrganizationService
from app.shared.idempotency import IdempotencyContext, IdempotencyService
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["organizations"])


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


def _now(request: Request) -> datetime:
    return getattr(request.state, "server_time", datetime.now(UTC))


def _org_service(session: AsyncSession, settings: Settings) -> OrganizationService:
    return OrganizationService(session, get_redis(settings), settings)


def _claim_service(session: AsyncSession, settings: Settings) -> ClaimService:
    return ClaimService(session, get_redis(settings), settings)


def _cover_service(session: AsyncSession, settings: Settings) -> CoverService:
    return CoverService(session, get_redis(settings), settings)


def _managed_service(session: AsyncSession, settings: Settings) -> ManagedVenueService:
    return ManagedVenueService(session, get_redis(settings), settings)


@router.post("/organizations")
async def create_organization(
    request: Request,
    body: CreateOrganizationRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _org_service(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.create_organization(user=ctx.user, name=body.name, now=now)
        return 201, success_response(data, meta=_meta(request)).model_dump(mode="json")

    status, body_out = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route="/v1/organizations",
            body={"name": body.name},
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return body_out


@router.get("/me/organizations")
async def list_my_organizations(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _org_service(session, settings).list_my_organizations(ctx.user)
    return success_response({"items": data}, meta=_meta(request)).model_dump(mode="json")


@router.get("/organizations/{organization_id}")
async def get_organization(
    request: Request,
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _org_service(session, settings).get_organization(ctx.user, organization_id)
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.get("/organizations/{organization_id}/members")
async def list_members(
    request: Request,
    organization_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _org_service(session, settings).list_members(ctx.user, organization_id)
    return success_response({"items": data}, meta=_meta(request)).model_dump(mode="json")


@router.post("/organizations/{organization_id}/invitations")
async def invite_member(
    request: Request,
    organization_id: UUID,
    body: CreateInvitationRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _org_service(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.invite_member(
            user=ctx.user,
            organization_id=organization_id,
            email=body.email,
            role=body.role,
            now=now,
        )
        return 201, success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
            mode="json"
        )

    status, body_out = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route=f"/v1/organizations/{organization_id}/invitations",
            body={"email": body.email, "role": body.role},
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return body_out


@router.patch("/organizations/{organization_id}/members/{user_id}")
async def update_member_role(
    request: Request,
    organization_id: UUID,
    user_id: UUID,
    body: UpdateMemberRoleRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _org_service(session, settings).update_member_role(
        user=ctx.user,
        organization_id=organization_id,
        target_user_id=user_id,
        role=body.role,
        now=_now(request),
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.delete("/organizations/{organization_id}/members/{user_id}")
async def remove_member(
    request: Request,
    organization_id: UUID,
    user_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _org_service(session, settings).remove_member(
        user=ctx.user,
        organization_id=organization_id,
        target_user_id=user_id,
        now=_now(request),
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.get("/organization-invitations/{token}")
async def get_invitation(
    request: Request,
    token: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    data = await _org_service(session, settings).get_invitation_by_token(token)
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/organization-invitations/{token}/accept")
async def accept_invitation(
    request: Request,
    token: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _org_service(session, settings).accept_invitation(
        user=ctx.user, token=token, now=_now(request)
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.post("/organization-invitations/{invitation_id}/revoke")
async def revoke_invitation(
    request: Request,
    invitation_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _org_service(session, settings).revoke_invitation(
        user=ctx.user, invitation_id=invitation_id, now=_now(request)
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.post("/venues/{venue_id}/claims")
async def submit_venue_claim(
    request: Request,
    venue_id: UUID,
    body: SubmitVenueClaimRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _claim_service(session, settings)
    now = _now(request)
    # Fingerprint omits evidence_reference / business_email (sensitive).
    fingerprint = {
        "venue_id": str(venue_id),
        "organization_id": str(body.organization_id) if body.organization_id else None,
        "requested_organization_name": body.requested_organization_name,
        "has_evidence": body.evidence_reference is not None,
        "has_business_email": body.business_email is not None,
        "justification": body.justification,
    }

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.submit_claim(user=ctx.user, venue_id=venue_id, body=body, now=now)
        return 201, success_response(data, meta=_meta(request)).model_dump(mode="json")

    status, body_out = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route=f"/v1/venues/{venue_id}/claims",
            body=fingerprint,
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return body_out


@router.get("/me/venue-claims")
async def list_my_venue_claims(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _claim_service(session, settings).list_my_claims(ctx.user)
    return success_response({"items": data}, meta=_meta(request)).model_dump(mode="json")


@router.post("/venue-claims/{claim_id}/cancel")
async def cancel_venue_claim(
    request: Request,
    claim_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _claim_service(session, settings).cancel_claim(
        user=ctx.user, claim_id=claim_id, now=_now(request)
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.patch("/venues/{venue_id}/managed-profile")
async def update_managed_profile(
    request: Request,
    venue_id: UUID,
    body: ManagedVenueProfileUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _managed_service(session, settings).update_managed_profile(
        user=ctx.user, venue_id=venue_id, body=body, now=_now(request)
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.put("/venues/{venue_id}/cover")
async def set_venue_cover(
    request: Request,
    venue_id: UUID,
    body: SetVenueCoverRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _cover_service(session, settings)
    now = _now(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.set_cover(
            user=ctx.user,
            venue_id=venue_id,
            media_asset_id=body.media_asset_id,
            now=now,
        )
        return 200, success_response(data, meta=_meta(request)).model_dump(mode="json")

    status, body_out = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="PUT",
            route=f"/v1/venues/{venue_id}/cover",
            body={"media_asset_id": str(body.media_asset_id)},
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return body_out


@router.delete("/venues/{venue_id}/cover")
async def remove_venue_cover(
    request: Request,
    venue_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    data = await _cover_service(session, settings).remove_cover(
        user=ctx.user, venue_id=venue_id, now=_now(request)
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")
