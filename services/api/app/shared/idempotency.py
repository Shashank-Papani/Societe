from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis

from app.core.errors import AppError
from app.shared.logging_redaction import stable_json_hash

IdempotencyHandler = Callable[[], Awaitable[tuple[int, dict[str, Any]]]]


@dataclass(frozen=True)
class IdempotencyContext:
    user_id: str
    method: str
    route: str
    body: Any
    key: str


class IdempotencyService:
    def __init__(self, redis: Redis[str], *, ttl_seconds: int = 86_400) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    def _storage_key(self, ctx: IdempotencyContext) -> str:
        return f"idempotency:{ctx.user_id}:{ctx.key}"

    def _fingerprint(self, ctx: IdempotencyContext) -> str:
        return stable_json_hash(
            {
                "method": ctx.method.upper(),
                "route": ctx.route,
                "body": ctx.body if ctx.body is not None else {},
            }
        )

    def _base_record(self, ctx: IdempotencyContext, fingerprint: str, state: str) -> dict[str, Any]:
        now = int(time.time())
        return {
            "state": state,
            "user_id": ctx.user_id,
            "method": ctx.method.upper(),
            "route": ctx.route,
            "body_fingerprint": fingerprint,
            "created_at": now,
            "expires_at": now + self._ttl,
        }

    async def run(
        self,
        ctx: IdempotencyContext,
        handler: IdempotencyHandler,
    ) -> tuple[int, dict[str, Any]]:
        storage_key = self._storage_key(ctx)
        fingerprint = self._fingerprint(ctx)
        processing_payload = json.dumps(self._base_record(ctx, fingerprint, "processing"))
        acquired = await self._redis.set(storage_key, processing_payload, nx=True, ex=self._ttl)
        if not acquired:
            existing_raw = await self._redis.get(storage_key)
            if existing_raw is None:
                acquired = await self._redis.set(
                    storage_key, processing_payload, nx=True, ex=self._ttl
                )
                if acquired:
                    return await self._execute(ctx, handler, storage_key, fingerprint)
                existing_raw = await self._redis.get(storage_key)
            if existing_raw is None:
                raise AppError(
                    "IDEMPOTENCY_CONFLICT",
                    "Could not acquire idempotency lock.",
                    status_code=409,
                )
            existing = json.loads(existing_raw)
            if (
                existing.get("body_fingerprint") != fingerprint
                or existing.get("method") != ctx.method.upper()
                or existing.get("route") != ctx.route
            ):
                raise AppError(
                    "IDEMPOTENCY_KEY_REUSE",
                    "Idempotency-Key was reused with a different request.",
                    status_code=409,
                )
            state = existing.get("state")
            if state == "processing":
                raise AppError(
                    "IDEMPOTENCY_REQUEST_IN_PROGRESS",
                    "A request with this Idempotency-Key is still processing.",
                    status_code=409,
                )
            if state == "completed":
                return int(existing["status_code"]), existing["body"]
            raise AppError(
                "IDEMPOTENCY_RETRYABLE",
                "Previous attempt failed; retry with a new Idempotency-Key or wait.",
                status_code=409,
            )

        return await self._execute(ctx, handler, storage_key, fingerprint)

    async def _execute(
        self,
        ctx: IdempotencyContext,
        handler: IdempotencyHandler,
        storage_key: str,
        fingerprint: str,
    ) -> tuple[int, dict[str, Any]]:
        try:
            status_code, body = await handler()
        except Exception:
            failed = self._base_record(ctx, fingerprint, "failed")
            existing_raw = await self._redis.get(storage_key)
            if existing_raw:
                existing = json.loads(existing_raw)
                if "created_at" in existing:
                    failed["created_at"] = existing["created_at"]
            await self._redis.set(storage_key, json.dumps(failed), ex=self._ttl)
            raise

        completed = self._base_record(ctx, fingerprint, "completed")
        existing_raw = await self._redis.get(storage_key)
        if existing_raw:
            existing = json.loads(existing_raw)
            if "created_at" in existing:
                completed["created_at"] = existing["created_at"]
        completed["status_code"] = status_code
        completed["body"] = body
        await self._redis.set(storage_key, json.dumps(completed), ex=self._ttl)
        return status_code, body
