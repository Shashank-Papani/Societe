from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import uuid4

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
from app.core.errors import AppError
from app.db.session import get_redis
from app.modules.presence.heartbeat import PresenceHeartbeatService
from app.modules.presence.schemas import (
    EligibilityRequest,
    EvidenceLocation,
    EvidenceRequest,
    HeartbeatRequest,
    LeaveRequest,
    PlatformSignals,
    PresenceData,
    SimulatorRequest,
)
from app.modules.presence.service import PresenceService
from app.shared.idempotency import IdempotencyContext, IdempotencyService
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(prefix="/v1", tags=["presence"])


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


def _received_at(request: Request) -> datetime:
    """Server clock only — client timestamps never drive dwell or lease math."""
    return getattr(request.state, "server_time", datetime.now(UTC))


def _presence_body(request: Request, data: PresenceData) -> dict[str, Any]:
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


def _service(session: AsyncSession, settings: Settings) -> PresenceService:
    return PresenceService(session, get_redis(settings), settings)


@router.post("/presence/evidence")
async def submit_evidence(
    request: Request,
    body: EvidenceRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    service = _service(session, settings)
    received_at = _received_at(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.submit_evidence(
            user=ctx.user,
            request=body,
            received_at=received_at,
        )
        return 200, _presence_body(request, data)

    status, body_out = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route="/v1/presence/evidence",
            # Coordinates stay out of the fingerprint; the client-generated
            # evidence_id already makes a retry uniquely identifiable.
            body={
                "evidence_id": str(body.evidence_id),
                "device_id": str(body.device_id),
                "client_sequence": body.client_sequence,
            },
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.evidence_idempotency_ttl_seconds,
    )
    response.status_code = status
    return body_out


@router.get("/presence/me")
async def get_presence_me(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    service = _service(session, settings)
    data = await service.get_me(ctx.user, now=_received_at(request))
    return _presence_body(request, data)


@router.post("/presence/eligibility")
async def evaluate_eligibility(
    request: Request,
    body: EligibilityRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Read-only eligibility preview for the selected venue.

    Does not create leases, evidence, or sample-buffer writes. The verify
    mutation remains the only path that grants presence.
    """
    service = _service(session, settings)
    data = await service.evaluate_eligibility(
        user=ctx.user,
        request=body,
        received_at=_received_at(request),
    )
    return success_response(data.model_dump(mode="json"), meta=_meta(request)).model_dump(
        mode="json"
    )


@router.post("/presence/heartbeat")
async def presence_heartbeat(
    request: Request,
    body: HeartbeatRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    """Renew or recheck active venue presence from location evidence."""
    service = PresenceHeartbeatService(session, get_redis(settings), settings)
    received_at = _received_at(request)

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.heartbeat(
            user=ctx.user,
            request=body,
            received_at=received_at,
            allow_simulated=settings.app_env in {"development", "test"},
        )
        return 200, _presence_body(request, data)

    status, body_out = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route="/v1/presence/heartbeat",
            body={
                "evidence_id": str(body.evidence_id),
                "device_id": str(body.device_id),
                "client_sequence": body.client_sequence,
                "venue_id": str(body.venue_id) if body.venue_id else None,
                "check_in_id": str(body.check_in_id) if body.check_in_id else None,
            },
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.evidence_idempotency_ttl_seconds,
    )
    response.status_code = status
    return body_out


@router.post("/presence/leave")
async def leave_presence(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
    idem: Annotated[IdempotencyService, Depends(get_idempotency_service)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    body: LeaveRequest | None = None,
) -> dict[str, Any]:
    service = _service(session, settings)
    received_at = _received_at(request)
    payload = (body or LeaveRequest()).model_dump(mode="json")

    async def handler() -> tuple[int, dict[str, Any]]:
        data = await service.leave(ctx.user, received_at=received_at)
        return 200, _presence_body(request, data)

    status, body_out = await idem.run(
        IdempotencyContext(
            user_id=str(ctx.user.id),
            method="POST",
            route="/v1/presence/leave",
            body=payload,
            key=idempotency_key,
        ),
        handler,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )
    response.status_code = status
    return body_out


@router.post("/dev/location/simulate")
async def simulate_location(
    request: Request,
    body: SimulatorRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    ctx: Annotated[CurrentUserContext, Depends(get_current_user)],
) -> dict[str, Any]:
    """Development-only. Runs the production engine with is_simulated=true."""
    if settings.app_env not in {"development", "test"} or not settings.ff_location_simulator:
        raise AppError("NOT_FOUND", "Not found.", status_code=404)

    received_at = _received_at(request)
    evidence = EvidenceRequest(
        evidence_id=uuid4(),
        observed_at=received_at,
        location=EvidenceLocation(
            latitude=body.latitude,
            longitude=body.longitude,
            horizontal_accuracy_m=body.horizontal_accuracy_m,
            altitude_m=body.altitude_m,
            speed_mps=body.speed_mps,
            provider=body.provider,
        ),
        platform_signals=PlatformSignals(
            is_mock=False,
            is_simulated=True,
            app_state="foreground",
        ),
        candidate_venue_id=body.candidate_venue_id,
        client_sequence=body.client_sequence,
        device_id=body.device_id,
    )
    service = _service(session, settings)
    data = await service.submit_evidence(
        user=ctx.user,
        request=evidence,
        received_at=received_at,
        allow_simulated=True,
    )
    return _presence_body(request, data)
