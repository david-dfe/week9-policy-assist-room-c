"""Slice H tests: prompt-injection anomaly signals on OTel spans.

The app must record per-request signal (question length + short hash of
the question, plus answer length) as span attributes so anomalies are
visible without ever writing user content to a durable store.

Hard invariant from CLAUDE.md §9.1: no raw question or answer text may
appear as a span attribute value.
"""

from __future__ import annotations

import hashlib
import importlib
import re
from pathlib import Path
from typing import Any

import pytest


class _StubMessage:
    def __init__(self, text: str = "stub-answer") -> None:
        self.content = text
        self.usage_metadata = {"input_tokens": 100, "output_tokens": 5}


class _StubLLM:
    def __init__(self) -> None:
        self.calls: list[list[Any]] = []
        self._answer = "stub-answer"

    def set_answer(self, text: str) -> None:
        self._answer = text

    def invoke(self, messages: list[Any]) -> _StubMessage:
        self.calls.append(messages)
        return _StubMessage(self._answer)


class _RecordingSpan:
    """Stand-in for the ``LLMSpan`` yielded by ``traced_llm_call``.

    Captures every ``set_attribute`` call so tests can assert on names
    and values without hitting the real OTel SDK.
    """

    def __init__(self) -> None:
        self.attributes: dict[str, Any] = {}
        self.usage_recorded_for: list[Any] = []

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def record_usage(self, response: Any) -> None:
        self.usage_recorded_for.append(response)


class _SpanFactory:
    """Callable replacement for ``traced_llm_call``.

    Each entry into the context manager yields a fresh ``_RecordingSpan``,
    stored on ``self.spans`` in insertion order.
    """

    def __init__(self) -> None:
        self.spans: list[_RecordingSpan] = []

    def __call__(self, *args: Any, **kwargs: Any) -> _SpanFactory:
        return self

    def __enter__(self) -> _RecordingSpan:
        span = _RecordingSpan()
        self.spans.append(span)
        return span

    def __exit__(self, *exc_info: Any) -> None:
        return None


@pytest.fixture
def app_and_spans(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Any, _StubLLM, _SpanFactory]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("SECRET_KEY", "test-secret-not-a-real-secret")
    monkeypatch.setenv("POLICYASSIST_HISTORY_ROOT", str(tmp_path))
    monkeypatch.delenv("HISTORY_MAX_TURNS", raising=False)
    monkeypatch.delenv("MAX_QUESTION_LENGTH", raising=False)

    import policyassist.config
    import policyassist.history

    importlib.reload(policyassist.config)
    importlib.reload(policyassist.history)

    import policyassist.app

    importlib.reload(policyassist.app)

    stub_llm = _StubLLM()
    monkeypatch.setattr(policyassist.app, "llm", stub_llm)

    factory = _SpanFactory()
    monkeypatch.setattr(policyassist.app, "traced_llm_call", factory)

    policyassist.app.app.config["TESTING"] = True
    return policyassist.app.app, stub_llm, factory


def test_question_length_recorded_on_span(
    app_and_spans: tuple[Any, _StubLLM, _SpanFactory],
) -> None:
    app, _llm, factory = app_and_spans
    question = "how do I inspect a HGV manifest?"
    with app.test_client() as client:
        client.get("/")
        client.post("/ask", json={"question": question})

    assert len(factory.spans) == 1
    assert factory.spans[0].attributes["policyassist.question.length"] == len(question)


def test_question_hash_recorded_on_span_and_is_8_hex_chars(
    app_and_spans: tuple[Any, _StubLLM, _SpanFactory],
) -> None:
    app, _llm, factory = app_and_spans
    question = "who is the duty higher officer?"
    with app.test_client() as client:
        client.get("/")
        client.post("/ask", json={"question": question})

    recorded = factory.spans[0].attributes["policyassist.question.hash"]
    assert isinstance(recorded, str)
    assert re.fullmatch(r"[0-9a-f]{8}", recorded), recorded
    expected = hashlib.sha256(question.encode("utf-8")).hexdigest()[:8]
    assert recorded == expected


def test_answer_length_recorded_on_span(
    app_and_spans: tuple[Any, _StubLLM, _SpanFactory],
) -> None:
    app, llm, factory = app_and_spans
    llm.set_answer("a somewhat longer stub answer for length assertion")
    with app.test_client() as client:
        client.get("/")
        client.post("/ask", json={"question": "any"})

    assert factory.spans[0].attributes["policyassist.answer.length"] == len(
        "a somewhat longer stub answer for length assertion"
    )


def test_raw_question_text_not_recorded_on_span_attributes(
    app_and_spans: tuple[Any, _StubLLM, _SpanFactory],
) -> None:
    app, llm, factory = app_and_spans
    question = "unique-canary-string-questions-never-on-spans"
    answer = "unique-canary-string-answers-never-on-spans"
    llm.set_answer(answer)
    with app.test_client() as client:
        client.get("/")
        client.post("/ask", json={"question": question})

    for key, value in factory.spans[0].attributes.items():
        # Neither the raw question nor the raw answer may appear anywhere
        # in the recorded attribute values (CLAUDE.md §9.1).
        if isinstance(value, str):
            assert question not in value, f"question leaked into {key}"
            assert answer not in value, f"answer leaked into {key}"


def test_two_different_questions_produce_different_hashes(
    app_and_spans: tuple[Any, _StubLLM, _SpanFactory],
) -> None:
    app, _llm, factory = app_and_spans
    with app.test_client() as client:
        client.get("/")
        client.post("/ask", json={"question": "question one"})
        client.post("/ask", json={"question": "question two"})

    hashes = [s.attributes["policyassist.question.hash"] for s in factory.spans]
    assert len(hashes) == 2
    assert hashes[0] != hashes[1]


def test_two_identical_questions_produce_identical_hashes(
    app_and_spans: tuple[Any, _StubLLM, _SpanFactory],
) -> None:
    app, _llm, factory = app_and_spans
    with app.test_client() as client:
        client.get("/")
        client.post("/ask", json={"question": "same question"})
        client.post("/ask", json={"question": "same question"})

    hashes = [s.attributes["policyassist.question.hash"] for s in factory.spans]
    assert len(hashes) == 2
    assert hashes[0] == hashes[1]
