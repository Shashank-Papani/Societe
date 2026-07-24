from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.core.errors import AppError
from app.shared.idempotency import IdempotencyContext, IdempotencyService


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CURSOR_HMAC_SECRET", "test-cursor-hmac-secret-0123456789abcdef01234567")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-production-0123456789abcdef")
    from app.core.config import get_settings

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_idempotency_concurrency_and_reuse() -> None:
    from app.core.config import get_settings
    from app.db.session import get_redis, reset_resource_globals

    reset_resource_globals()
    redis = get_redis(get_settings())
    service = IdempotencyService(redis, ttl_seconds=60)
    key = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    ctx = IdempotencyContext(
        user_id=user_id,
        method="POST",
        route="/v1/me/devices",
        body={"platform": "ios"},
        key=key,
    )

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_handler() -> tuple[int, dict[str, object]]:
        started.set()
        await release.wait()
        return 200, {"data": {"ok": True}, "meta": {}, "error": None}

    task = asyncio.create_task(service.run(ctx, slow_handler))
    await started.wait()

    with pytest.raises(AppError) as in_progress:
        await service.run(ctx, slow_handler)
    assert in_progress.value.code == "IDEMPOTENCY_REQUEST_IN_PROGRESS"

    release.set()
    status, body = await task
    assert status == 200
    assert body["data"]["ok"] is True

    # Replay completed
    status2, body2 = await service.run(ctx, slow_handler)
    assert status2 == 200
    assert body2 == body

    # Same key, different body
    reuse = IdempotencyContext(
        user_id=user_id,
        method="POST",
        route="/v1/me/devices",
        body={"platform": "android"},
        key=key,
    )
    with pytest.raises(AppError) as reuse_exc:
        await service.run(reuse, slow_handler)
    assert reuse_exc.value.code == "IDEMPOTENCY_KEY_REUSE"


@pytest.mark.asyncio
async def test_idempotency_stores_fingerprint_fields() -> None:
    from app.core.config import get_settings
    from app.db.session import get_redis, reset_resource_globals

    reset_resource_globals()
    redis = get_redis(get_settings())
    service = IdempotencyService(redis, ttl_seconds=60)
    key = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    ctx = IdempotencyContext(
        user_id=user_id,
        method="POST",
        route="/v1/demo",
        body={"a": 1},
        key=key,
    )

    async def handler() -> tuple[int, dict[str, object]]:
        return 201, {"ok": True}

    await service.run(ctx, handler)
    raw = await redis.get(f"idempotency:{user_id}:{key}")
    assert raw is not None
    stored = json.loads(raw)
    assert stored["state"] == "completed"
    assert stored["user_id"] == user_id
    assert stored["method"] == "POST"
    assert stored["route"] == "/v1/demo"
    assert "body_fingerprint" in stored
    assert stored["status_code"] == 201
    assert stored["body"] == {"ok": True}
