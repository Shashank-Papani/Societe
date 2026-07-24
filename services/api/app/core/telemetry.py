from __future__ import annotations

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def setup_telemetry(app: FastAPI, settings: Settings) -> None:
    """OpenTelemetry foundation. OTLP export is optional and off by default."""
    if not settings.otel_enabled:
        return

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)

    if settings.otel_exporter_otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter: OTLPSpanExporter | ConsoleSpanExporter = OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint
            )
        except Exception as exc:
            logger.warning("otlp_exporter_unavailable", error=str(exc))
            exporter = ConsoleSpanExporter()
    else:
        exporter = ConsoleSpanExporter()

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:
        logger.warning("fastapi_instrumentation_unavailable", error=str(exc))
