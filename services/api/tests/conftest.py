from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from media_support import MediaWorld

    from app.core.config import Settings
    from app.modules.media.storage import ObjectStorage


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_PROVIDER", "local")
    # Isolate from developer .env (e.g. local-dev-user-b for dual-simulator work).
    monkeypatch.setenv("LOCAL_DEV_SUBJECT", "local-dev-user")
    monkeypatch.setenv("LOCAL_DEV_HANDLE", "localdev")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-production-0123456789abcdef")
    monkeypatch.setenv("CURSOR_HMAC_SECRET", "test-cursor-hmac-secret-0123456789abcdef01234567")
    monkeypatch.setenv("EMAIL_PROVIDER", "memory")
    monkeypatch.setenv("OTEL_ENABLED", "false")
    # Phase 3 media posting is exercised by the suite, so the flag is on and the
    # development-only scanner/moderator are selected explicitly rather than
    # inherited from whatever the developer has in .env.
    monkeypatch.setenv("FF_MEDIA_POSTING", "true")
    monkeypatch.setenv("FF_CALLING_CARDS", "true")
    monkeypatch.setenv("FF_PRIVATE_MESSAGING", "true")
    monkeypatch.setenv("MEDIA_MALWARE_SCANNER", "noop")
    monkeypatch.setenv("MEDIA_MODERATION_PROVIDER", "fake")
    monkeypatch.setenv("MINIO_PUBLIC_ENDPOINT", "http://localhost:9000")
    monkeypatch.setenv("REALTIME_PROVIDER", "local")
    monkeypatch.setenv("PUSH_PROVIDER", "local")
    # Keep dispatcher push-fallback tests fast (ack wait is polled once).
    monkeypatch.setenv("REALTIME_ACK_WAIT_SECONDS", "0.05")
    monkeypatch.setenv("REALTIME_ACK_TTL_SECONDS", "60")
    from app.core.config import get_settings
    from app.db.session import reset_resource_globals

    get_settings.cache_clear()
    reset_resource_globals()
    yield
    get_settings.cache_clear()
    reset_resource_globals()


@pytest.fixture
def client(_test_env: None) -> Iterator[TestClient]:
    from app.main import create_app

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def database_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://societe:societe@localhost:5432/societe",
    )


@pytest.fixture
def valkey_url() -> str:
    return os.getenv("VALKEY_URL", "redis://localhost:6379/0")


# --------------------------------------------------------------- media (Phase 3)
#
# The media pipeline is tested against the real Compose stack: presigned URLs,
# skip-locked job claiming, and cascade behaviour are precisely what a mocked
# object store or database would hide. Missing infrastructure skips.


@pytest.fixture
def media_settings(_test_env: None) -> Settings:
    from app.core.config import get_settings

    return get_settings()


@pytest.fixture
async def db_session(media_settings: Settings) -> AsyncIterator[AsyncSession]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(media_settings.database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        pytest.skip("PostgreSQL is not reachable; run `make dev-up`")

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def valkey(media_settings: Settings) -> AsyncIterator[Redis[str]]:
    client: Redis[str] = Redis.from_url(media_settings.valkey_url, decode_responses=True)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        pytest.skip("Valkey is not reachable; run `make dev-up`")
    yield client
    await client.aclose()


@pytest.fixture
async def object_storage(media_settings: Settings) -> AsyncIterator[ObjectStorage]:
    from app.modules.media.storage import build_object_storage

    storage = build_object_storage(media_settings)
    try:
        await storage.ensure_buckets()
    except Exception:
        pytest.skip("MinIO is not reachable; run `make dev-up`")
    yield storage


@pytest.fixture
async def media_world(
    db_session: AsyncSession,
    valkey: Redis[str],
    media_settings: Settings,
) -> AsyncIterator[MediaWorld]:
    from media_support import build_world

    world = await build_world(db_session, valkey, media_settings)
    try:
        yield world
    finally:
        await world.cleanup()
