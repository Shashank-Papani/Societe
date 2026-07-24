from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.db.session import check_postgres, check_valkey
from app.shared.schemas import ApiMeta, success_response

router = APIRouter(tags=["health"])


class LiveData(BaseModel):
    status: str = "ok"


class ReadyDependency(BaseModel):
    name: str
    status: str
    detail: str | None = None


class ReadyData(BaseModel):
    status: str
    dependencies: list[ReadyDependency]


def _meta(request: Request) -> ApiMeta:
    return ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        server_time=getattr(request.state, "server_time", datetime.now(UTC)),
    )


@router.get("/health/live")
async def health_live(request: Request) -> dict[str, Any]:
    """Liveness: process is up. Does not check dependencies."""
    return success_response(LiveData(), meta=_meta(request)).model_dump(mode="json")


@router.get("/health/ready")
async def health_ready(request: Request, response: Response) -> dict[str, Any]:
    """Readiness: required dependencies are reachable."""
    settings: Settings = get_settings()
    deps: list[ReadyDependency] = []
    overall = "ok"

    try:
        await check_postgres(settings)
        deps.append(ReadyDependency(name="postgres", status="ok"))
    except Exception as exc:
        overall = "degraded"
        deps.append(ReadyDependency(name="postgres", status="error", detail=str(exc)))

    try:
        await check_valkey(settings)
        deps.append(ReadyDependency(name="valkey", status="ok"))
    except Exception as exc:
        overall = "degraded"
        deps.append(ReadyDependency(name="valkey", status="error", detail=str(exc)))

    if overall != "ok":
        response.status_code = 503

    return success_response(
        ReadyData(status=overall, dependencies=deps),
        meta=_meta(request),
    ).model_dump(mode="json")
