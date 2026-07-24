from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("AUTH_PROVIDER", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret-not-for-production-0123456789abcdef")
    monkeypatch.setenv("CURSOR_HMAC_SECRET", "test-cursor-hmac-secret-0123456789abcdef01234567")
    monkeypatch.setenv("OTEL_ENABLED", "false")
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
