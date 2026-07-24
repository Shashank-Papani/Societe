from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.deps import CurrentUserContext, get_current_user, get_db
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.modules.venues.filters import MapVenuesQuery, VenueCategory
from app.modules.venues.service import VenueService
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["venues"])


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


@router.get("/map/venues")
async def map_venues(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    _ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    latitude: float = Query(...),
    longitude: float = Query(...),
    radius_m: int = Query(3000, ge=50, le=25_000),
    music_tags: list[str] | None = Query(default=None),
    experience_tags: list[str] | None = Query(default=None),
    price_bands: list[int] | None = Query(default=None),
    categories: list[VenueCategory] | None = Query(default=None),
    minimum_age: int | None = Query(default=None, ge=18, le=25),
    age_bands: list[str] | None = Query(default=None),
    crowd_buckets: list[str] | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(20, ge=1, le=50),
) -> dict[str, Any]:
    # Reject future analytics filters before pydantic model (explicit 400 code).
    if age_bands is not None:
        raise AppError(
            "FILTER_NOT_AVAILABLE",
            "age_bands depends on live venue analytics and is not available yet.",
            status_code=400,
        )
    if crowd_buckets is not None:
        raise AppError(
            "FILTER_NOT_AVAILABLE",
            "crowd_buckets depends on live venue analytics and is not available yet.",
            status_code=400,
        )

    query = MapVenuesQuery(
        latitude=latitude,
        longitude=longitude,
        radius_m=radius_m,
        music_tags=music_tags or [],
        experience_tags=experience_tags or [],
        price_bands=price_bands or [],
        categories=categories or [],
        minimum_age=minimum_age,
        cursor=cursor,
        limit=limit,
    )
    service = VenueService(session, settings)
    data = await service.map_venues(query)
    return success_response(data, meta=_meta(request)).model_dump(mode="json")


@router.get("/venues/{venue_id}")
async def get_venue(
    request: Request,
    venue_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    _ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = VenueService(session, settings)
    data = await service.get_public_detail(venue_id)
    return success_response(data, meta=_meta(request)).model_dump(mode="json")
