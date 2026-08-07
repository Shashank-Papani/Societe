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
from app.modules.identity.auth_router import router as auth_router
from app.modules.identity.router import router as identity_router
from app.modules.media.router import router as media_router
from app.modules.messaging.router import router as messaging_router
from app.modules.notifications.router import router as notifications_router
from app.modules.organizations import admin_router as organizations_admin_router
from app.modules.organizations import router as organizations_router
from app.modules.presence.router import router as presence_router
from app.modules.realtime.router import router as realtime_router
from app.modules.social.router import router as social_router
from app.modules.stories.router import router as stories_router
from app.modules.venues.router import router as venues_router
from app.modules.vibes.router import router as vibes_router

logger = get_logger(__name__)

# Story / official-content response models returned inside ApiSuccess envelopes.
# Routes use dict payloads for idempotency compatibility; register them so
# OpenAPI still documents the public contract.
_STORY_OPENAPI_MODELS = (
    "StoryUploadResponse",
    "StoryGroupSummary",
    "StoryGroupDetail",
    "StorySlide",
    "StoryGroupListResponse",
    "RecordStoryViewResponse",
    "CreateStoryReportResponse",
    "DeleteStoryResponse",
    "OfficialPostSummary",
    "OfficialPostDetail",
    "OfficialPostCreateResponse",
    "OfficialPostListResponse",
    "OfficialPostUpload",
    "UploadInstruction",
    "StoryAuthorProjection",
    "VenueStoryProjection",
)


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
    application.include_router(auth_router)
    application.include_router(identity_router)
    application.include_router(venues_router)
    application.include_router(presence_router)
    application.include_router(media_router)
    application.include_router(vibes_router)
    application.include_router(stories_router)
    application.include_router(social_router)
    application.include_router(messaging_router)
    application.include_router(notifications_router)
    application.include_router(realtime_router)
    application.include_router(organizations_router)
    application.include_router(organizations_admin_router)

    setup_telemetry(application, settings)

    def custom_openapi() -> dict[str, Any]:
        if application.openapi_schema is not None:
            return application.openapi_schema
        from fastapi.openapi.utils import get_openapi

        from app.modules.stories import schemas as story_schemas

        schema = get_openapi(
            title=application.title,
            version=application.version,
            routes=application.routes,
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for name in _STORY_OPENAPI_MODELS:
            model = getattr(story_schemas, name, None)
            if model is None:
                continue
            model_schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
            # Flatten $defs into components so refs resolve.
            defs = model_schema.pop("$defs", {})
            for def_name, def_schema in defs.items():
                components.setdefault(def_name, def_schema)
            components[name] = model_schema
        application.openapi_schema = schema
        return schema

    application.openapi = custom_openapi  # type: ignore[method-assign]
    return application


app = create_app()
