"""OpenTelemetry instrumentation for LLM calls.

Public API:

- :func:`instrument_app` — configure the global OTel tracer provider.
- :func:`traced_llm_call` — context manager around a single LLM call.

Domain guardrail (CLAUDE.md §9 rule 1): raw prompt or completion text
must never be set as a span attribute. Only metadata (tokens, model,
cost, latency, session id, error class) is emitted.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from monitoring.cost import Usage, compute_cost, usage_from_response

_TRACER_NAME = "monitoring"
_INSTRUMENTED = False


def instrument_app(service_name: str | None = None) -> None:
    """Configure global OTel tracing for the current process.

    Idempotent — subsequent calls are no-ops. Reads OTLP endpoint config
    from standard ``OTEL_EXPORTER_OTLP_*`` env vars.
    """
    global _INSTRUMENTED
    if _INSTRUMENTED:
        return
    if service_name is None:
        service_name = os.environ.get("OTEL_SERVICE_NAME", "unknown-app")
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _INSTRUMENTED = True


class LLMSpan:
    """Wrapper around an OTel Span with LLM-aware helpers.

    Callers get a ``LLMSpan`` from :func:`traced_llm_call` and typically
    only need ``record_usage(response)``. Direct attribute setting via
    ``set_attribute`` is available for anything not covered by the
    GenAI semantic conventions.
    """

    def __init__(self, span: Span, model: str) -> None:
        self._span = span
        self._model = model

    def record_usage(self, response: Any) -> Usage:
        """Extract usage from an LLM response and set span attributes.

        Returns the parsed :class:`Usage` so callers can log or assert on it.
        """
        usage = usage_from_response(response)
        self._span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
        self._span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)
        self._span.set_attribute(
            "gen_ai.usage.cache_read_input_tokens", usage.cache_read_input_tokens
        )
        self._span.set_attribute(
            "gen_ai.usage.cache_creation_input_tokens",
            usage.cache_creation_input_tokens,
        )
        self._span.set_attribute("cost.gbp", compute_cost(self._model, usage))
        return usage

    def set_attribute(self, key: str, value: str | int | float | bool) -> None:
        self._span.set_attribute(key, value)


@contextmanager
def traced_llm_call(
    model: str,
    *,
    session_id: str | None = None,
    system: str = "anthropic",
) -> Iterator[LLMSpan]:
    """Start a span around a single LLM invocation.

    Sets GenAI semantic-convention attributes at entry. Exceptions raised
    inside the ``with`` block are recorded on the span and re-raised.

    Example::

        with traced_llm_call(model="claude-sonnet-4-5", session_id=sid) as span:
            response = llm.invoke(messages)
            span.record_usage(response)
    """
    tracer = trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span("llm.invoke", kind=SpanKind.CLIENT) as raw_span:
        raw_span.set_attribute("gen_ai.system", system)
        raw_span.set_attribute("gen_ai.request.model", model)
        if session_id is not None:
            raw_span.set_attribute("app.session_id", session_id)
        wrapped = LLMSpan(raw_span, model)
        try:
            yield wrapped
        except Exception as exc:
            raw_span.set_status(Status(StatusCode.ERROR, str(exc)))
            raw_span.record_exception(exc)
            raw_span.set_attribute("error.class", type(exc).__name__)
            raise
