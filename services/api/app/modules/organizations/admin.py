"""Development/test admin routes for venue claim review.

When ``ff_venue_claim_admin`` is enabled and ``app_env`` is development or
test, only allowlisted development subjects (currently Dev Alpha) may approve
or reject claims. This is a fixture mechanism for local integration tests —
not a production admin role model. These routes must never be enabled in
staging or production (enforced by Settings validation). When the flag is
off or the environment is wrong, endpoints return 404 to avoid enumeration.

Authorization uses the immutable ``auth_subject`` only — never handle,
display name, or any client-supplied admin flag/header/body field.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import CurrentUserContext, get_current_user, get_db
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import get_redis
from app.modules.identity.dev_personas import DEV_VENUE_CLAIM_ADMIN_SUBJECTS
from app.modules.organizations.claims import ClaimService
from app.modules.organizations.schemas import RejectVenueClaimRequest
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1/admin", tags=["organizations-admin"])


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


def _now(request: Request) -> datetime:
    return getattr(request.state, "server_time", datetime.now(UTC))


def _require_claim_admin(settings: Settings, ctx: CurrentUserContext) -> None:
    if settings.app_env not in {"development", "test"} or not settings.ff_venue_claim_admin:
        raise AppError("NOT_FOUND", "Not found.", status_code=404)

    if ctx.user.auth_subject not in DEV_VENUE_CLAIM_ADMIN_SUBJECTS:
        raise AppError(
            "FORBIDDEN",
            "You are not authorized to review venue claims.",
            status_code=403,
        )


@router.post("/venue-claims/{claim_id}/approve")
async def approve_venue_claim(
    request: Request,
    claim_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    _require_claim_admin(settings, ctx)
    data = await ClaimService(session, get_redis(settings), settings).approve_claim(
        admin_user=ctx.user, claim_id=claim_id, now=_now(request)
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.post("/venue-claims/{claim_id}/reject")
async def reject_venue_claim(
    request: Request,
    claim_id: UUID,
    body: RejectVenueClaimRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    _require_claim_admin(settings, ctx)
    data = await ClaimService(session, get_redis(settings), settings).reject_claim(
        admin_user=ctx.user,
        claim_id=claim_id,
        reason=body.reason,
        now=_now(request),
    )
    return success_response(data, meta=_meta(request)).model_dump(mode="json")
