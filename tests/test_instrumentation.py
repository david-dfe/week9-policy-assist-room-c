"""Tests for OTel instrumentation."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from monitoring.instrumentation import traced_llm_call


@pytest.fixture
def span_capture() -> Iterator[InMemorySpanExporter]:
    """Install an in-memory span exporter for the duration of the test."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with patch.object(trace, "_TRACER_PROVIDER", provider):
        yield exporter


class _FakeResponse:
    """Stand-in for a LangChain ChatAnthropic response."""

    def __init__(self, usage: dict[str, int]) -> None:
        self.usage_metadata = usage


class TestTracedLLMCall:
    def test_sets_base_attributes(self, span_capture: InMemorySpanExporter) -> None:
        with traced_llm_call("claude-haiku-4-5", session_id="s1"):
            pass
        spans = span_capture.get_finished_spans()
        assert len(spans) == 1
        span = spans[0]
        assert span.name == "llm.invoke"
        assert span.attributes is not None
        assert span.attributes["gen_ai.system"] == "anthropic"
        assert span.attributes["gen_ai.request.model"] == "claude-haiku-4-5"
        assert span.attributes["app.session_id"] == "s1"

    def test_no_session_id_no_attribute(self, span_capture: InMemorySpanExporter) -> None:
        with traced_llm_call("claude-haiku-4-5"):
            pass
        span = span_capture.get_finished_spans()[0]
        assert span.attributes is not None
        assert "app.session_id" not in span.attributes

    def test_custom_system(self, span_capture: InMemorySpanExporter) -> None:
        with traced_llm_call("some-model", system="openai"):
            pass
        span = span_capture.get_finished_spans()[0]
        assert span.attributes is not None
        assert span.attributes["gen_ai.system"] == "openai"

    def test_exception_recorded_and_reraised(self, span_capture: InMemorySpanExporter) -> None:
        with pytest.raises(RuntimeError, match="boom"):  # noqa: SIM117
            with traced_llm_call("claude-haiku-4-5"):
                raise RuntimeError("boom")
        span = span_capture.get_finished_spans()[0]
        assert span.attributes is not None
        assert span.status.status_code.name == "ERROR"
        assert span.attributes["error.class"] == "RuntimeError"

    def test_record_usage_sets_all_attributes(self, span_capture: InMemorySpanExporter) -> None:
        response = _FakeResponse(
            {
                "input_tokens": 1_000,
                "output_tokens": 500,
                "cache_read_input_tokens": 10_000,
                "cache_creation_input_tokens": 0,
            }
        )
        with traced_llm_call("claude-haiku-4-5") as span:
            usage = span.record_usage(response)
        assert usage.input_tokens == 1_000

        span_data = span_capture.get_finished_spans()[0]
        assert span_data.attributes is not None
        assert span_data.attributes["gen_ai.usage.input_tokens"] == 1_000
        assert span_data.attributes["gen_ai.usage.output_tokens"] == 500
        assert span_data.attributes["gen_ai.usage.cache_read_input_tokens"] == 10_000
        assert span_data.attributes["gen_ai.usage.cache_creation_input_tokens"] == 0
        # claude-haiku-4-5 from real prices.yaml:
        # (1000 * 0.80 + 500 * 4.00 + 10000 * 0.08) / 1e6
        #   = (800 + 2000 + 800) / 1e6 = 3600 / 1e6 = 0.0036 GBP
        assert span_data.attributes["cost.gbp"] == pytest.approx(0.0036)

    def test_set_attribute_passthrough(self, span_capture: InMemorySpanExporter) -> None:
        with traced_llm_call("claude-haiku-4-5") as span:
            span.set_attribute("app.custom", "value")
        span_data = span_capture.get_finished_spans()[0]
        assert span_data.attributes is not None
        assert span_data.attributes["app.custom"] == "value"

    def test_span_kind_is_client(self, span_capture: InMemorySpanExporter) -> None:
        """LLM calls are outbound network calls — SpanKind.CLIENT is required for
        SigNoz to render them as external dependencies in service maps."""
        with traced_llm_call("claude-haiku-4-5"):
            pass
        span = span_capture.get_finished_spans()[0]
        assert span.kind == SpanKind.CLIENT
