from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class ApiMeta(BaseModel):
    request_id: str
    server_time: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ApiErrorBody(BaseModel):
    data: None = None
    meta: ApiMeta
    error: ApiError


class ApiSuccess[T](BaseModel):
    data: T
    meta: ApiMeta
    error: None = None


def success_response[T](data: T, *, meta: ApiMeta) -> ApiSuccess[T]:
    return ApiSuccess(data=data, meta=meta)


def error_response(error: ApiError, *, meta: ApiMeta) -> ApiErrorBody:
    return ApiErrorBody(meta=meta, error=error)
