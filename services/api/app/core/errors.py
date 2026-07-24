from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.shared.schemas import ApiError, ApiMeta, error_response


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    meta = ApiMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
    )
    body = error_response(
        ApiError(code=exc.code, message=exc.message, details=exc.details),
        meta=meta,
    )
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    meta = ApiMeta(request_id=getattr(request.state, "request_id", "unknown"))
    code = "HTTP_ERROR"
    details: dict[str, Any]
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        code = str(exc.detail["code"])
        message = str(exc.detail.get("message", exc.detail))
        details = {k: v for k, v in exc.detail.items() if k not in {"code", "message"}}
    else:
        message = str(exc.detail)
        details = {}
    body = error_response(ApiError(code=code, message=message, details=details), meta=meta)
    return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    meta = ApiMeta(request_id=getattr(request.state, "request_id", "unknown"))
    body = error_response(
        ApiError(
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            details={"errors": exc.errors()},
        ),
        meta=meta,
    )
    return JSONResponse(status_code=422, content=body.model_dump(mode="json"))
