from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_redis: Redis[str] | None = None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    global _engine, _session_factory
    if _engine is None:
        cfg = settings or get_settings()
        _engine = create_async_engine(
            cfg.database_url,
            pool_pre_ping=True,
            future=True,
        )
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_session_factory(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        get_engine(settings)
    assert _session_factory is not None
    return _session_factory


async def get_db_session() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


def get_redis(settings: Settings | None = None) -> Redis[str]:
    global _redis
    if _redis is None:
        cfg = settings or get_settings()
        _redis = Redis.from_url(cfg.valkey_url, decode_responses=True)
    return _redis


async def check_postgres(settings: Settings | None = None) -> None:
    engine = get_engine(settings)
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def check_valkey(settings: Settings | None = None) -> None:
    client = get_redis(settings)
    if not await client.ping():
        raise RuntimeError("Valkey ping failed")


async def dispose_resources() -> None:
    global _engine, _session_factory, _redis
    if _redis is not None:
        close = getattr(_redis, "aclose", None) or _redis.close
        result: Any = close()
        if hasattr(result, "__await__"):
            await result
        _redis = None
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
