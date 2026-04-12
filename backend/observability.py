"""Prometheus metrics and optional OpenTelemetry wiring for FinEdgar."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any, Iterator

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

    PROMETHEUS_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency fallback
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"
    PROMETHEUS_AVAILABLE = False


if PROMETHEUS_AVAILABLE:
    HTTP_REQUESTS = Counter(
        "finedgar_http_requests_total",
        "HTTP requests handled by FinEdgar.",
        ["method", "path", "status"],
    )
    HTTP_LATENCY = Histogram(
        "finedgar_http_request_duration_seconds",
        "HTTP request latency in seconds.",
        ["method", "path"],
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
    )
    CHAT_REQUESTS = Counter(
        "finedgar_chat_requests_total",
        "Chat requests handled by the answer pipeline.",
        ["route", "status"],
    )
    CHAT_LATENCY = Histogram(
        "finedgar_chat_duration_seconds",
        "Chat pipeline latency in seconds.",
        ["route"],
        buckets=(0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
    )
    OLLAMA_REQUESTS = Counter(
        "finedgar_ollama_requests_total",
        "Ollama generate calls made by FinEdgar.",
        ["status"],
    )
    OLLAMA_LATENCY = Histogram(
        "finedgar_ollama_request_duration_seconds",
        "Ollama generate call latency in seconds.",
        ["status"],
        buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
    )
    PIPELINE_ERRORS = Counter(
        "finedgar_pipeline_errors_total",
        "Pipeline errors by stage.",
        ["stage"],
    )


def _enabled(value: str | None) -> bool:
    return str(value or "").lower() in {"1", "true", "yes", "on"}


def render_metrics() -> tuple[bytes, str]:
    if not PROMETHEUS_AVAILABLE:
        return b"# prometheus_client is not installed\n", CONTENT_TYPE_LATEST
    return generate_latest(), CONTENT_TYPE_LATEST


def observe_http(method: str, path: str, status: int, elapsed_seconds: float) -> None:
    if not PROMETHEUS_AVAILABLE:
        return
    HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
    HTTP_LATENCY.labels(method=method, path=path).observe(elapsed_seconds)


def observe_chat(route: str, status: str, elapsed_seconds: float) -> None:
    if not PROMETHEUS_AVAILABLE:
        return
    normalized_route = route or "unknown"
    CHAT_REQUESTS.labels(route=normalized_route, status=status).inc()
    CHAT_LATENCY.labels(route=normalized_route).observe(elapsed_seconds)


def observe_ollama(status: str, elapsed_seconds: float) -> None:
    if not PROMETHEUS_AVAILABLE:
        return
    OLLAMA_REQUESTS.labels(status=status).inc()
    OLLAMA_LATENCY.labels(status=status).observe(elapsed_seconds)


def observe_pipeline_error(stage: str) -> None:
    if not PROMETHEUS_AVAILABLE:
        return
    PIPELINE_ERRORS.labels(stage=stage or "unknown").inc()


@contextmanager
def traced_span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[None]:
    if not _enabled(os.getenv("FINEDGAR_OTEL_ENABLED")):
        yield
        return
    try:
        from opentelemetry import trace

        tracer = trace.get_tracer("finedgar")
        with tracer.start_as_current_span(name) as span:
            for key, value in (attributes or {}).items():
                span.set_attribute(key, value)
            yield
    except Exception:
        yield


def setup_opentelemetry(app: Any) -> None:
    if not _enabled(os.getenv("FINEDGAR_OTEL_ENABLED")):
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except Exception:
        return

    resource = Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "finedgar-web")})
    provider = TracerProvider(resource=resource)
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector.observability:4317")
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()


def monotonic_seconds() -> float:
    return time.perf_counter()
