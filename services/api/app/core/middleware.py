from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.shared.logging_redaction import LOCATION_QUERY_FIELDS, redact_mapping


def redact_query_string(query: str) -> str:
    pairs = parse_qsl(query, keep_blank_values=True)
    redacted = [
        (key, "[REDACTED]" if key.lower() in LOCATION_QUERY_FIELDS else value)
        for key, value in pairs
    ]
    return urlencode(redacted)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        request.state.server_time = datetime.now(UTC)

        safe_query = redact_query_string(request.url.query)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=request.url.path,
            method=request.method,
            query=safe_query or None,
        )

        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response


def redact_error_details(details: dict[str, object]) -> dict[str, object]:
    return redact_mapping(details)
