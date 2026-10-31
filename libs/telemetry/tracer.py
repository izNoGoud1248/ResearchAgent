from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SimpleSpanProcessor


class Tracer:
    """One trace per research run, carried across HTTP, MCP, A2A and the job queue as a W3C traceparent."""

    tracerName = "researchdesk"

    @staticmethod
    def setup(serviceName: str, endpoint: str | None = None, exporter: SpanExporter | None = None) -> TracerProvider:
        provider = TracerProvider(resource=Resource.create({"service.name": serviceName}))
        if exporter is not None:
            provider.add_span_processor(SimpleSpanProcessor(exporter))
        if endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
        trace.set_tracer_provider(provider)
        return provider

    @staticmethod
    @contextmanager
    def span(
        name: str,
        carrier: Mapping[str, str] | None = None,
        expected: tuple[type[BaseException], ...] = (),
        **attributes: Any,
    ) -> Iterator[trace.Span]:
        """Starts a span. With a carrier, the span continues the trace that sent it.

        Exceptions listed in `expected` are control flow (such as a graph pausing for approval), not errors.
        """
        context = propagate.extract(Tracer.lowerKeys(carrier)) if carrier is not None else None
        tracer = trace.get_tracer(Tracer.tracerName)
        with tracer.start_as_current_span(
            name, context=context, attributes=Tracer.clean(attributes), record_exception=False, set_status_on_exception=False
        ) as current:
            try:
                yield current
            except expected:
                raise
            except Exception as error:
                current.record_exception(error)
                current.set_status(trace.StatusCode.ERROR, f"{type(error).__name__}: {error}"[:200])
                raise

    @staticmethod
    def inject(headers: dict[str, str] | None = None) -> dict[str, str]:
        carrier = dict(headers or {})
        propagate.inject(carrier)
        return carrier

    @staticmethod
    def currentTraceId() -> str:
        return format(trace.get_current_span().get_span_context().trace_id, "032x")

    @staticmethod
    def currentSpanId() -> str:
        return format(trace.get_current_span().get_span_context().span_id, "016x")

    @staticmethod
    def traceIdFrom(traceparent: str) -> str:
        parts = traceparent.split("-")
        return parts[1] if len(parts) == 4 else ""

    @staticmethod
    def lowerKeys(carrier: Mapping[str, str]) -> dict[str, str]:
        # HTTP header names arrive in any case; the W3C propagator looks for lower case.
        return {key.lower(): value for key, value in carrier.items()}

    @staticmethod
    def clean(attributes: dict[str, Any]) -> dict[str, str | int | float | bool]:
        return {key: value for key, value in attributes.items() if isinstance(value, (str, int, float, bool))}
