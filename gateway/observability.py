# built-in
import json
import logging
import os
from datetime import datetime, timezone

# third-party
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        context = {
            key: getattr(record, key)
            for key in ("approval_id", "action", "upstream_url", "event_type")
            if hasattr(record, key)
        }
        if context:
            payload["context"] = context
        return json.dumps(payload, separators=(",", ":"))


def configure_observability(app) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        framework_logger = logging.getLogger(logger_name)
        framework_logger.handlers = [handler]
        framework_logger.propagate = False

    resource = Resource.create(
        {"service.name": os.getenv("OTEL_SERVICE_NAME", "self-healing-gateway")}
    )
    tracer_provider = TracerProvider(resource=resource)
    metric_readers = []

    if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        metric_readers.append(
            PeriodicExportingMetricReader(
                OTLPMetricExporter(), export_interval_millis=30_000
            )
        )

    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=metric_readers)
    )
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/health")
    HTTPXClientInstrumentor().instrument()


_meter = metrics.get_meter("gateway.operations")
health_checks = _meter.create_counter(
    "gateway.health_checks", description="Upstream health checks"
)
healing_sessions = _meter.create_counter(
    "gateway.healing_sessions", description="AI-assisted healing sessions"
)
proxied_requests = _meter.create_counter(
    "gateway.proxied_requests", description="Requests forwarded to upstreams"
)
