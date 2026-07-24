from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    validation_error_handler,
)
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.telemetry import setup_telemetry
from app.db.session import dispose_resources
from app.modules.identity.router import router as identity_router

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, json_logs=settings.app_env != "development")
    logger.info(
        "api_starting",
        app_env=settings.app_env,
        auth_provider=settings.auth_provider,
    )
    yield
    await dispose_resources()
    logger.info("api_stopped")


def create_app() -> FastAPI:
    # Validate settings (including local-auth guard) at import/startup.
    settings = get_settings()

    application = FastAPI(
        title="Société API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.app_env in {"development", "test"} else None,
        redoc_url="/redoc" if settings.app_env in {"development", "test"} else None,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.app_env in {"development", "test"} else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(RequestContextMiddleware)

    application.add_exception_handler(AppError, cast(Any, app_error_handler))
    application.add_exception_handler(StarletteHTTPException, cast(Any, http_error_handler))
    application.add_exception_handler(RequestValidationError, cast(Any, validation_error_handler))

    application.include_router(health_router)
    application.include_router(identity_router)

    setup_telemetry(application, settings)
    return application


app = create_app()
